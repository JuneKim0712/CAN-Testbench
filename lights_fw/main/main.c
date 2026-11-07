// ==============================================================================
// BRAKELIGHTS ESP32 (DUAL I2C, CAN RX/TX, AND TRANSITION STATE MACHINE)
// Implements an explicit state machine with non-blocking cooperative checks.
// ==============================================================================

#include <stdio.h>
#include <stdlib.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"
#include "driver/gpio.h"
#include "driver/ledc.h"         
#include "driver/i2c_master.h"   
#include "esp_adc/adc_oneshot.h" 
#include "CAN.h"                 
#include "led_strip.h"          

static const char *TAG = "Brakelights_ESP32";

// --- PIN & BUS DEFINITIONS ---
#define PIN_BUTTON              GPIO_NUM_8  
#define PIN_HAZARDS_LED         GPIO_NUM_36 
#define PIN_PEDALS_LED          GPIO_NUM_35 
#define PIN_POT_LED             GPIO_NUM_37 
#define PIN_POT_ADC             ADC_CHANNEL_3 
#define PIN_ACTIVE_LED          3           

#define I2C_MASTER_SCL_IO       GPIO_NUM_14 
#define I2C_MASTER_SDA_IO       GPIO_NUM_13 
#define I2C_MASTER_NUM          I2C_NUM_0 
#define I2C_MASTER_FREQ_HZ      100000 
#define I2C_MASTER_TIMEOUT_MS   1000 
#define LTC4151_SENSOR_ADDR     0x69 

// --- GLOBALS & HANDLES ---
typedef enum {
    STATE_IDLE = 0,
    STATE_ACTIVE
} system_state_t;

volatile system_state_t current_state = STATE_IDLE;
volatile bool hazards_enabled = false;
volatile uint8_t global_power_payload = 0; 

i2c_master_bus_handle_t bus_handle;
i2c_master_dev_handle_t ltc_handle;
adc_oneshot_unit_handle_t adc1_handle;
static led_strip_handle_t led_strip;


// --- I2C HELPER FUNCTIONS ---
static esp_err_t ltc4151_register_read(i2c_master_dev_handle_t dev_handle, uint8_t reg_addr, uint8_t *data, size_t len) 
{
    return i2c_master_transmit_receive(dev_handle, &reg_addr, 1, data, len, I2C_MASTER_TIMEOUT_MS); 
}

static void i2c_master_init(i2c_master_bus_handle_t *b_handle, i2c_master_dev_handle_t *d_handle) 
{
    i2c_master_bus_config_t bus_config = { 
        .i2c_port = I2C_MASTER_NUM, 
        .sda_io_num = I2C_MASTER_SDA_IO, 
        .scl_io_num = I2C_MASTER_SCL_IO, 
        .clk_source = I2C_CLK_SRC_DEFAULT, 
        .glitch_ignore_cnt = 7, 
        .flags.enable_internal_pullup = false, 
    };
    ESP_ERROR_CHECK(i2c_new_master_bus(&bus_config, b_handle)); 

    i2c_device_config_t dev_config = { 
        .dev_addr_length = I2C_ADDR_BIT_LEN_7, 
        .device_address = LTC4151_SENSOR_ADDR, 
        .scl_speed_hz = I2C_MASTER_FREQ_HZ, 
    };
    ESP_ERROR_CHECK(i2c_master_bus_add_device(*b_handle, &dev_config, d_handle)); 
}

void setup_pwm_led(gpio_num_t pin, ledc_channel_t channel) 
{
    ledc_timer_config_t ledc_timer = {
        .speed_mode       = LEDC_LOW_SPEED_MODE,
        .timer_num        = LEDC_TIMER_0,
        .duty_resolution  = LEDC_TIMER_8_BIT, 
        .freq_hz          = 5000, 
        .clk_cfg          = LEDC_AUTO_CLK
    };
    ledc_timer_config(&ledc_timer);

    ledc_channel_config_t ledc_channel = {
        .speed_mode     = LEDC_LOW_SPEED_MODE,
        .channel        = channel,
        .timer_sel      = LEDC_TIMER_0,
        .intr_type      = LEDC_INTR_DISABLE,
        .gpio_num       = pin,
        .duty           = 0, 
        .hpoint         = 0
    };
    ledc_channel_config(&ledc_channel);
}


// --- I2C POWER MONITOR TASK ---
void power_monitor_task(void *arg)
{
    i2c_master_dev_handle_t ltc_dev_handle = (i2c_master_dev_handle_t)arg;
    uint8_t data[2];

    while (1) {
        if (current_state != STATE_ACTIVE) {
            vTaskDelay(pdMS_TO_TICKS(50));
            continue;
        }

        esp_err_t ret = ltc4151_register_read(ltc_dev_handle, 0x02, data, 2);

        if (ret == ESP_OK) {
            uint16_t raw_adc = (data[0] << 4) | (data[1] >> 4);
            float voltage = raw_adc * 0.025f;
            
            global_power_payload = (uint8_t)(voltage * 10.0f);
            ESP_LOGI(TAG, "I2C Read SUCCESS! Local Voltage: %.2f V | Payload Byte: %d", voltage, global_power_payload);
        } else {
            // FAILSAFE: Default to 0 if the sensor read fails
            global_power_payload = 0;
            ESP_LOGE(TAG, "Failed to read I2C sensor. Defaulting to 0V. Error: %s", esp_err_to_name(ret));
        }
        vTaskDelay(pdMS_TO_TICKS(1000)); 
    }
}

// --- BONUS POTENTIOMETER TASK ---
void bonus_pot_task(void *arg) 
{
    int raw_adc;
    uint8_t last_logged_brightness = 0;

    while (1) {
        if (current_state != STATE_ACTIVE) {
            vTaskDelay(pdMS_TO_TICKS(50));
            continue;
        }

        ESP_ERROR_CHECK(adc_oneshot_read(adc1_handle, PIN_POT_ADC, &raw_adc));
        uint8_t brightness = (uint8_t)(raw_adc >> 4); 
        
        ledc_set_duty(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_1, brightness);
        ledc_update_duty(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_1);

        if (abs((int)brightness - (int)last_logged_brightness) > 2 || 
           (brightness == 0 && last_logged_brightness != 0) || 
           (brightness == 255 && last_logged_brightness != 255)) {
            
            ESP_LOGI(TAG, "Bonus Potentiometer Value: %d | Setting GPIO 37 PWM Duty", brightness);
            last_logged_brightness = brightness;
        }

        vTaskDelay(pdMS_TO_TICKS(50)); 
    }
}


// --- TRANSMIT TASKS ---
void can_tx_task(void *arg) 
{
    uint8_t loop_count = 0; 
    TickType_t last_wake_time = xTaskGetTickCount();

    while (1) {
        if (current_state != STATE_ACTIVE) {
            vTaskDelay(pdMS_TO_TICKS(50));
            last_wake_time = xTaskGetTickCount();
            continue;
        }

        CAN_message_t hb_msg = {0};
        hb_msg.id = 0x02;
        hb_msg.dlc = 1;
        hb_msg.data[0] = 0x00;
        esp_err_t ret1 = CAN_send(&hb_msg, 50);
        if (ret1 != ESP_OK) {
            ESP_LOGW(TAG, "CAN_send 0x02 heartbeat failed: %s", esp_err_to_name(ret1));
        }
        
        CAN_message_t pwr_msg = {0};
        pwr_msg.id = 0x21;
        pwr_msg.dlc = 1;
        pwr_msg.data[0] = global_power_payload; 
        esp_err_t ret2 = CAN_send(&pwr_msg, 50);
        if (ret2 != ESP_OK) {
            ESP_LOGW(TAG, "CAN_send 0x21 power failed: %s", esp_err_to_name(ret2));
        }

        loop_count++;
        if (loop_count >= 10) { 
            ESP_LOGI(TAG, "TX [0x02] Heartbeat Sent | TX [0x21] Power Sent: %d (%.1f V)", global_power_payload, global_power_payload / 10.0f);
            loop_count = 0;
        }

        vTaskDelayUntil(&last_wake_time, pdMS_TO_TICKS(100)); 
    }
}

// --- RECEIVE TASKS ---
void can_rx_task(void *arg) 
{
    uint8_t last_logged_pedal = 0;

    while (1) {
        if (current_state != STATE_ACTIVE) {
            vTaskDelay(pdMS_TO_TICKS(50));
            continue;
        }

        CAN_message_t rx_msg;
        esp_err_t ret = CAN_receive(&rx_msg, 100);
        
        if (ret == ESP_OK) {
            if (rx_msg.rtr || rx_msg.extended) {
                continue;
            }

            switch (rx_msg.id) {
                case 0x01: 
                    if (rx_msg.dlc >= 2) {
                        ESP_LOGI(TAG, "RX [0x01] Pedals Status Received! Power Byte: %d (%.1f V)", rx_msg.data[1], rx_msg.data[1] / 10.0f);
                    }
                    break;
                
                case 0x11: 
                    if (rx_msg.dlc >= 1) {
                        ledc_set_duty(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_0, rx_msg.data[0]); 
                        ledc_update_duty(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_0);
                        
                        if (abs((int)rx_msg.data[0] - (int)last_logged_pedal) > 2 || 
                           (rx_msg.data[0] == 0 && last_logged_pedal != 0) || 
                           (rx_msg.data[0] == 255 && last_logged_pedal != 255)) {
                            
                            ESP_LOGI(TAG, "RX [0x11] Pedal Position: %d | Dimming GPIO 35", rx_msg.data[0]);
                            last_logged_pedal = rx_msg.data[0];
                        }
                    }
                    break;
                
                case 0x12: 
                    if (rx_msg.dlc >= 1) {
                        hazards_enabled = (rx_msg.data[0] == 0x01);
                        ESP_LOGW(TAG, "RX [0x12] Hazards Toggle Received! | State: %s", hazards_enabled ? "ON" : "OFF");
                    }
                    break;
            }
        }
        // Direct queue sleep in CAN_receive controls loop timing
    }
}

// --- HAZARDS TASK ---
void hazards_task(void *arg) 
{
    bool led_state = false;
    while (1) {
        if (current_state != STATE_ACTIVE) {
            gpio_set_level(PIN_HAZARDS_LED, 0);
            led_state = false;
            vTaskDelay(pdMS_TO_TICKS(50));
            continue;
        }

        if (hazards_enabled) {
            led_state = !led_state;
            gpio_set_level(PIN_HAZARDS_LED, led_state);
        } else {
            gpio_set_level(PIN_HAZARDS_LED, 0); 
            led_state = false;
        }
        vTaskDelay(pdMS_TO_TICKS(500)); 
    }
}


// --- STARTUP BUTTON TASK ---
void startup_btn_task(void *arg) 
{
    bool last_btn_state = true; 

    while (1) {
        bool current_btn_state = gpio_get_level(PIN_BUTTON);

        if (last_btn_state == true && current_btn_state == false) {
            vTaskDelay(pdMS_TO_TICKS(30)); 
            
            if (gpio_get_level(PIN_BUTTON) == false) { 
                
                if (current_state == STATE_IDLE) {
                    current_state = STATE_ACTIVE;
                    ESP_LOGI(TAG, "=== STATE CHANGE: Brakelights Transitioning to ACTIVE ===");
                    
                    led_strip_set_pixel(led_strip, 0, 0, 255, 0); 
                    led_strip_refresh(led_strip);
                } else {
                    current_state = STATE_IDLE;
                    ESP_LOGW(TAG, "=== STATE CHANGE: Brakelights Transitioning to IDLE ===");
                    
                    gpio_set_level(PIN_HAZARDS_LED, 0);
                    ledc_set_duty(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_0, 0); 
                    ledc_update_duty(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_0);
                    ledc_set_duty(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_1, 0); 
                    ledc_update_duty(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_1);
                }
            }
        }
        last_btn_state = current_btn_state;
        vTaskDelay(pdMS_TO_TICKS(10)); 
    }
}

// --- IDLE LED TASK ---
void idle_led_task(void *arg) 
{
    bool toggle = false;
    while (1) {
        if (current_state == STATE_IDLE) {
            toggle = !toggle;
            if (toggle) {
                led_strip_set_pixel(led_strip, 0, 0, 0, 255); 
                led_strip_refresh(led_strip);
                ESP_LOGI(TAG, "[IDLE MODE] Waiting for Startup Button on GPIO 8...");
            } else {
                led_strip_clear(led_strip); 
            }
            vTaskDelay(pdMS_TO_TICKS(500)); 
        } else {
            vTaskDelay(pdMS_TO_TICKS(100)); 
        }
    }
}


// --- MAIN ENTRY POINT ---
void app_main(void) 
{
    vTaskDelay(pdMS_TO_TICKS(2000)); 
    
    ESP_LOGI(TAG, "================================================");
    ESP_LOGI(TAG, "Brakelights ESP32 Booting Up...");
    ESP_LOGI(TAG, "================================================");

    // 1. Configure Basic GPIOs
    gpio_set_direction(PIN_BUTTON, GPIO_MODE_INPUT);
    gpio_set_pull_mode(PIN_BUTTON, GPIO_PULLUP_ONLY); 
    
    gpio_reset_pin(PIN_HAZARDS_LED);
    gpio_set_direction(PIN_HAZARDS_LED, GPIO_MODE_OUTPUT);

    // 2. Configure Addressable RGB LED 
    led_strip_config_t strip_config = {
        .strip_gpio_num = PIN_ACTIVE_LED,
        .max_leds = 1, 
    };
    led_strip_rmt_config_t rmt_config = {
        .resolution_hz = 10 * 1000 * 1000, 
        .flags.with_dma = false,
    };
    ESP_ERROR_CHECK(led_strip_new_rmt_device(&strip_config, &rmt_config, &led_strip));
    led_strip_clear(led_strip);

    // 3. Setup PWM & ADC
    setup_pwm_led(PIN_PEDALS_LED, LEDC_CHANNEL_0); 
    setup_pwm_led(PIN_POT_LED, LEDC_CHANNEL_1);    
    
    adc_oneshot_unit_init_cfg_t init_config1 = { .unit_id = ADC_UNIT_1 };
    ESP_ERROR_CHECK(adc_oneshot_new_unit(&init_config1, &adc1_handle));
    adc_oneshot_chan_cfg_t config = {
        .bitwidth = ADC_BITWIDTH_DEFAULT,
        .atten = ADC_ATTEN_DB_12,
    };
    ESP_ERROR_CHECK(adc_oneshot_config_channel(adc1_handle, PIN_POT_ADC, &config));

    // 4. Initialize I2C & CAN
    i2c_master_init(&bus_handle, &ltc_handle);
    ESP_ERROR_CHECK(CAN_init());
    ESP_LOGI(TAG, "Drivers Initialized. Starting pinned tasks...");

    // 5. Start Pinned Tasks with return status validation
    BaseType_t ret;
    ret = xTaskCreatePinnedToCore(startup_btn_task, "startup_btn", 4096, NULL, 5, NULL, 1);
    ESP_ERROR_CHECK(ret == pdPASS ? ESP_OK : ESP_FAIL);

    ret = xTaskCreatePinnedToCore(idle_led_task, "idle_led", 2048, NULL, 1, NULL, 1);
    ESP_ERROR_CHECK(ret == pdPASS ? ESP_OK : ESP_FAIL);
    
    ret = xTaskCreatePinnedToCore(can_tx_task, "can_tx", 4096, NULL, 3, NULL, 1); 
    ESP_ERROR_CHECK(ret == pdPASS ? ESP_OK : ESP_FAIL);

    ret = xTaskCreatePinnedToCore(power_monitor_task, "power_monitor", 4096, (void *)ltc_handle, 2, NULL, 1);
    ESP_ERROR_CHECK(ret == pdPASS ? ESP_OK : ESP_FAIL);

    ret = xTaskCreatePinnedToCore(can_rx_task, "can_rx", 4096, NULL, 4, NULL, 1);
    ESP_ERROR_CHECK(ret == pdPASS ? ESP_OK : ESP_FAIL);

    ret = xTaskCreatePinnedToCore(hazards_task, "hazards", 2048, NULL, 2, NULL, 1);
    ESP_ERROR_CHECK(ret == pdPASS ? ESP_OK : ESP_FAIL);

    ret = xTaskCreatePinnedToCore(bonus_pot_task, "bonus_pot", 4096, NULL, 2, NULL, 1);
    ESP_ERROR_CHECK(ret == pdPASS ? ESP_OK : ESP_FAIL);

    // 6. Keep app_main alive 
    while (1) {
        vTaskDelay(pdMS_TO_TICKS(1000)); 
    }
}
