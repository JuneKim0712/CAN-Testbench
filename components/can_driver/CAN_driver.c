#include "CAN.h"
#include "esp_log.h"
#include <stdio.h>
#include "freertos/semphr.h"

//private
static twai_node_handle_t s_node = NULL;
static QueueHandle_t s_rx_queue = NULL;
static volatile uint32_t s_rx_queue_overflows = 0;
static volatile uint32_t s_tx_errors = 0;
static portMUX_TYPE s_stats_mux = portMUX_INITIALIZER_UNLOCKED;
// Initialized during single-owner startup; retained across driver restarts.
static SemaphoreHandle_t s_api_mutex;
static SemaphoreHandle_t s_rx_mutex;
static twai_frame_t s_tx_frame;
static uint8_t s_tx_data[8];
static bool s_tx_pending;
static volatile bool s_tx_success;

static bool IRAM_ATTR CAN_tx_cb(twai_node_handle_t handle,
                               const twai_tx_done_event_data_t *event, void *context)
{
    (void)handle;
    (void)context;
    s_tx_success = event->is_tx_success;
    return false;
}

uint32_t CAN_get_rx_overflow_count(void)
{
    portENTER_CRITICAL(&s_stats_mux);
    uint32_t count = s_rx_queue_overflows;
    portEXIT_CRITICAL(&s_stats_mux);
    return count;
}

uint32_t CAN_get_tx_error_count(void)
{
    portENTER_CRITICAL(&s_stats_mux);
    uint32_t count = s_tx_errors;
    portEXIT_CRITICAL(&s_stats_mux);
    return count;
}

static void count_tx_error(void)
{
    portENTER_CRITICAL(&s_stats_mux);
    s_tx_errors++;
    portEXIT_CRITICAL(&s_stats_mux);
}

//ISR-context RX callback
static bool IRAM_ATTR CAN_rx_cb(twai_node_handle_t handle,
                                const twai_rx_done_event_data_t *edata,
                                void *user_ctx)
{
    (void)edata;
    (void)user_ctx;

    if (s_rx_queue == NULL) return false;

    uint8_t recv_buff[8] = {0};

    twai_frame_t rx_frame = {
        .buffer     = recv_buff,
        .buffer_len = sizeof(recv_buff),   // capacity
    };

    if (twai_node_receive_from_isr(handle, &rx_frame) != ESP_OK) {
        return false;
    }

    CAN_message_t msg = {0};
    msg.id       = rx_frame.header.id;
    msg.extended = rx_frame.header.ide;
    msg.rtr      = rx_frame.header.rtr;
    msg.dlc      = (uint8_t)rx_frame.header.dlc;

    if (!msg.rtr) {
        size_t n = msg.dlc;
        if (n > 8) n = 8;
        memcpy(msg.data, recv_buff, n);
    }

    BaseType_t hp_task_woken = pdFALSE;
    BaseType_t send_res = xQueueSendFromISR(s_rx_queue, &msg, &hp_task_woken);
    if (send_res != pdPASS) {
        portENTER_CRITICAL_ISR(&s_stats_mux);
        s_rx_queue_overflows++;
        portEXIT_CRITICAL_ISR(&s_stats_mux);
    }

    if (hp_task_woken == pdTRUE) {
        portYIELD_FROM_ISR();
        return true;
    }
    return false;
}

esp_err_t CAN_init(void)
{
    if (s_api_mutex == NULL) {
        s_api_mutex = xSemaphoreCreateMutex();
        if (s_api_mutex == NULL) return ESP_ERR_NO_MEM;
    }
    if (s_rx_mutex == NULL) {
        s_rx_mutex = xSemaphoreCreateMutex();
        if (s_rx_mutex == NULL) return ESP_ERR_NO_MEM;
    }
    if (s_node != NULL) return ESP_ERR_INVALID_STATE;

    // RX queue used to bridge ISR callback, user blocking receive
    s_rx_queue = xQueueCreate(16, sizeof(CAN_message_t));
    if (s_rx_queue == NULL) return ESP_ERR_NO_MEM;

    // Create on-chip TWAI engine at 500k bitrate
    twai_onchip_node_config_t node_config = {
        .io_cfg.tx = CAN_TX,
        .io_cfg.rx = CAN_RX,
        .io_cfg.quanta_clk_out = GPIO_NUM_NC,
        .io_cfg.bus_off_indicator = GPIO_NUM_NC,

        .bit_timing.bitrate = 500000,
        .tx_queue_depth = 8,
#ifdef CONFIG_CAN_SELF_TEST
        .flags.enable_self_test = 1,
#endif
    };

    esp_err_t ret = twai_new_node_onchip(&node_config, &s_node);
    if (ret != ESP_OK) {
        vQueueDelete(s_rx_queue);
        s_rx_queue = NULL;
        s_node = NULL;
        return ret;
    }

    // Register RX callback BEFORE enabling node
    twai_event_callbacks_t cbs = {
        .on_rx_done = CAN_rx_cb,
        .on_tx_done = CAN_tx_cb,
    };

    ret = twai_node_register_event_callbacks(s_node, &cbs, NULL);
    if (ret != ESP_OK) {
        twai_node_delete(s_node);
        s_node = NULL;
        vQueueDelete(s_rx_queue);
        s_rx_queue = NULL;
        return ret;
    }

    //Enable node (go online)
    ret = twai_node_enable(s_node);
    if (ret != ESP_OK) {
        twai_node_delete(s_node);
        s_node = NULL;
        vQueueDelete(s_rx_queue);
        s_rx_queue = NULL;
        return ret;
    }

    return ESP_OK;
}

esp_err_t CAN_deinit(void)
{
    if (s_node == NULL) return ESP_ERR_INVALID_STATE;
    if (xSemaphoreTake(s_api_mutex, 0) != pdTRUE) return ESP_ERR_INVALID_STATE;
    if (xSemaphoreTake(s_rx_mutex, 0) != pdTRUE) {
        xSemaphoreGive(s_api_mutex);
        return ESP_ERR_INVALID_STATE;
    }

    esp_err_t ret = twai_node_disable(s_node);
    if (ret != ESP_OK) {
        xSemaphoreGive(s_rx_mutex);
        xSemaphoreGive(s_api_mutex);
        return ret;
    }

    ret = twai_node_delete(s_node);
    if (ret != ESP_OK) {
        xSemaphoreGive(s_rx_mutex);
        xSemaphoreGive(s_api_mutex);
        return ret;
    }

    s_node = NULL;
    s_tx_pending = false;

    if (s_rx_queue) {
        vQueueDelete(s_rx_queue);
        s_rx_queue = NULL;
    }

    xSemaphoreGive(s_rx_mutex);
    xSemaphoreGive(s_api_mutex);
    return ESP_OK;
}

esp_err_t CAN_send(const CAN_message_t *frame, uint32_t timeout_ms)
{
    if (frame == NULL) return ESP_ERR_INVALID_ARG;
    if (s_node == NULL) return ESP_ERR_INVALID_STATE;

    // Validate ID and DLC bounds
    if (!frame->extended && frame->id > 0x7FF) {
        return ESP_ERR_INVALID_ARG;
    }
    if (frame->extended && frame->id > 0x1FFFFFFF) {
        return ESP_ERR_INVALID_ARG;
    }
    if (frame->dlc > 8) {
        return ESP_ERR_INVALID_ARG;
    }

    if (xSemaphoreTake(s_api_mutex, pdMS_TO_TICKS(timeout_ms)) != pdTRUE) return ESP_ERR_TIMEOUT;
    if (s_node == NULL) {
        xSemaphoreGive(s_api_mutex);
        return ESP_ERR_INVALID_STATE;
    }
    // A previous caller may have timed out while hardware still owns the frame.
    if (s_tx_pending) {
        esp_err_t pending = twai_node_transmit_wait_all_done(s_node, 0);
        if (pending != ESP_OK) {
            xSemaphoreGive(s_api_mutex);
            return pending;
        }
        s_tx_pending = false;
    }
    uint8_t *buf = s_tx_data;
    memset(buf, 0, sizeof(s_tx_data));
    size_t len = frame->dlc;
    if (len > 8) len = 8;

    if (!frame->rtr) {
        memcpy(buf, frame->data, len);
    } else {
        len = 0;
    }

    s_tx_frame = (twai_frame_t){
        .header.id  = frame->id,
        .header.ide = frame->extended,
        .header.rtr = frame->rtr,
        .header.dlc = frame->dlc,
        .buffer     = (len > 0) ? buf : NULL,
        .buffer_len = len,
    };

    // Fast inline hex formatting without snprintf overhead for high-throughput CAN telemetry
    static const char hex_chars[] = "0123456789ABCDEF";
    char hex_buf[17] = {0};
    for (size_t i = 0; i < len; i++) {
        hex_buf[i * 2]     = hex_chars[(buf[i] >> 4) & 0x0F];
        hex_buf[i * 2 + 1] = hex_chars[buf[i] & 0x0F];
    }
    hex_buf[len * 2] = '\0';
    ESP_LOGD("CAN", "[CAN_FRAME] ID:0x%03lX DLC:%zu DATA:%s", (unsigned long)frame->id, len, hex_buf);

    // Node API timeouts are in milliseconds 
    s_tx_success = false;
    esp_err_t ret = twai_node_transmit(s_node, &s_tx_frame, (int)timeout_ms);
    if (ret != ESP_OK) {
        count_tx_error();
        xSemaphoreGive(s_api_mutex);
        return ret;
    }
    s_tx_pending = true;
    //Ensure local buffer is no longer needed before returning 
    ret = twai_node_transmit_wait_all_done(s_node, (int)timeout_ms);
    if (ret == ESP_OK) {
        s_tx_pending = false;
        if (!s_tx_success) ret = ESP_FAIL;
    }
    if (ret != ESP_OK) {
        count_tx_error();
    } else {
        s_tx_pending = false;
    }
    xSemaphoreGive(s_api_mutex);
    return ret;
}

esp_err_t CAN_receive(CAN_message_t *frame, uint32_t timeout_ms)
{
    if (s_rx_queue == NULL) return ESP_ERR_INVALID_STATE;
    if (frame == NULL)      return ESP_ERR_INVALID_ARG;
    if (xSemaphoreTake(s_rx_mutex, 0) != pdTRUE) return ESP_ERR_TIMEOUT;
    if (s_rx_queue == NULL) {
        xSemaphoreGive(s_rx_mutex);
        return ESP_ERR_INVALID_STATE;
    }

    //0xFFFFFFFF for no timeout
    TickType_t to = (timeout_ms == 0xFFFFFFFF) ? portMAX_DELAY
                                               : pdMS_TO_TICKS(timeout_ms);

    esp_err_t ret = xQueueReceive(s_rx_queue, frame, to) == pdTRUE ? ESP_OK : ESP_ERR_TIMEOUT;
    xSemaphoreGive(s_rx_mutex);
    return ret;
}

esp_err_t CAN_build_packet(uint32_t id, const uint8_t *data, uint8_t dlc, CAN_message_t *out)
{
    if (out == NULL || id > 0x7FF || dlc > 8 || (dlc && data == NULL)) return ESP_ERR_INVALID_ARG;
    CAN_message_t message = {.id = id, .dlc = dlc};
    if (dlc) memcpy(message.data, data, dlc);
    *out = message;
    return ESP_OK;
}

CAN_message_t build_packet_no_ext(uint32_t id, const uint8_t *data, uint8_t dlc)
{
    CAN_message_t msg = {0};

    msg.id       = id;
    msg.extended = 0;   // standard frame
    msg.rtr      = 0;   // data frame

    if (dlc == 0) dlc = 8;   // default = 8
    if (dlc > 8)  dlc = 8;
    msg.dlc = dlc;

    if (data != NULL) {
        memcpy(msg.data, data, msg.dlc);
    }

    return msg;
}

twai_node_handle_t CAN_get_node_handle(void)
{
    return s_node;
}
