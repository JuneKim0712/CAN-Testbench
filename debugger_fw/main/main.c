// Binary-only legacy bridge: physical RX -> USB, validated USB command -> CAN.
// Standard data frames only; no logs or TX echoes enter the capture stream.
#include "CAN.h"
#include "driver/usb_serial_jtag.h"
#include "esp_log.h"

static size_t encode(const uint8_t *input, size_t length, uint8_t *output)
{
    size_t code_index = 0, written = 1;
    uint8_t code = 1;
    for (size_t i = 0; i < length; i++) {
        if (input[i] == 0) {
            output[code_index] = code;
            code_index = written++;
            code = 1;
        } else {
            output[written++] = input[i];
            code++;
        }
    }
    output[code_index] = code;
    output[written++] = 0;
    return written;
}

static void inject(const uint8_t *encoded, size_t length)
{
    // Reserved diagnostic query, not a CAN frame: COBS([0xF1]). Response
    // uses an impossible legacy DLC (15), so capture clients cannot mistake
    // controller status for physical traffic.
    if (length == 2 && encoded[0] == 2 && encoded[1] == 0xF1) {
        twai_node_status_t status;
        twai_node_record_t record;
        if (twai_node_get_info(CAN_get_node_handle(), &status, &record) == ESP_OK) {
            uint8_t raw[] = {0xF1, 0xF0, 1, status.state,
                status.tx_error_count & 255, status.rx_error_count & 255,
                gpio_get_level(CAN_RX), gpio_get_level(CAN_TX),
                record.bus_err_num & 255};
            uint8_t output[sizeof(raw) + 2];
            size_t size = encode(raw, sizeof(raw), output);
            (void)usb_serial_jtag_write_bytes(output, size, pdMS_TO_TICKS(10));
        }
        return;
    }
    uint8_t raw[11];
    size_t read = 0, written = 0;
    while (read < length) {
        uint8_t code = encoded[read++];
        if (code == 0 || read + code - 1 > length) return;
        for (unsigned i = 1; i < code; i++) {
            if (written >= sizeof(raw)) return;
            raw[written++] = encoded[read++];
        }
        if (code < 255 && read < length) {
            if (written >= sizeof(raw)) return;
            raw[written++] = 0;
        }
    }
    if (written < 3) return;
    uint8_t sum = 0;
    for (size_t i = 0; i < written; i++) sum += raw[i];
    uint8_t dlc = raw[1] >> 4;
    uint32_t id = raw[0] | ((uint32_t)(raw[1] & 15) << 8);
    if (sum || dlc > 8 || written != dlc + 3 || id > 0x7FF) return;
    CAN_message_t message = {.id = id, .dlc = dlc};
    memcpy(message.data, raw + 2, dlc);
    // Host request acceptance is not a CAN completion acknowledgment.
    (void)CAN_send(&message, 20);
}

void app_main(void)
{
    esp_log_level_set("*", ESP_LOG_NONE);
    usb_serial_jtag_driver_config_t usb = USB_SERIAL_JTAG_DRIVER_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(usb_serial_jtag_driver_install(&usb));
    ESP_ERROR_CHECK(CAN_init());
    uint8_t command[16], incoming[64];
    size_t command_length = 0;
    bool discard = false;
    while (1) {
        CAN_message_t message;
        if (CAN_receive(&message, 1) == ESP_OK && !message.extended &&
            !message.rtr && message.id <= 0x7FF && message.dlc <= 8) {
            uint8_t raw[11], output[13];
            raw[0] = message.id & 255;
            raw[1] = (message.dlc << 4) | ((message.id >> 8) & 15);
            memcpy(raw + 2, message.data, message.dlc);
            uint8_t sum = 0;
            for (unsigned i = 0; i < message.dlc + 2; i++) sum += raw[i];
            raw[message.dlc + 2] = (uint8_t)(0 - sum);
            size_t length = encode(raw, message.dlc + 3, output);
            // Drop a failed USB write rather than blocking CAN reception forever.
            (void)usb_serial_jtag_write_bytes(output, length, pdMS_TO_TICKS(10));
        }
        int count = usb_serial_jtag_read_bytes(incoming, sizeof(incoming), 0);
        for (int i = 0; i < count; i++) {
            if (incoming[i] == 0) {
                if (!discard && command_length) inject(command, command_length);
                command_length = 0;
                discard = false;
            } else if (!discard) {
                if (command_length == sizeof(command)) discard = true;
                else command[command_length++] = incoming[i];
            }
        }
    }
}
