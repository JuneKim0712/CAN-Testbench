// ==============================================================================
// PEDALS ESP32 (FULL SYSTEM SIMULATOR WITH VERBOSE LOGGING)
// Reads physical inputs, I2C power, sends CAN data, and monitors Brakelights.
// ==============================================================================


#include <stdio.h>
#include <stdlib.h> 
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"
#include "driver/gpio.h"
#include "driver/i2c_master.h"   
#include "esp_adc/adc_oneshot.h" 
#include "CAN.h"                 
#include "led_strip.h" 


static const char *TAG = "Pedals_ESP32";

// --- PIN & BUS DEFINITIONS ---
#define PIN_HAZARDS_BTN         GPIO_NUM_8  
#define PIN_PEDAL_POT           ADC_CHANNEL_3 
#define PIN_INDICATOR_LED       GPIO_NUM_42  
#define PIN_RGB_LED             3 

#define I2C_MASTER_SCL_IO       GPIO_NUM_14 
#define I2C_MASTER_SDA_IO       GPIO_NUM_13 
#define I2C_MASTER_NUM          I2C_NUM_0 
#define I2C_MASTER_FREQ_HZ      100000 
#define I2C_MASTER_TIMEOUT_MS   1000 
#define LTC4151_SENSOR_ADDR     0x69 

// --- GLOBALS & HANDLES ---
adc_oneshot_unit_handle_t adc1_handle;
static led_strip_handle_t led_strip; 

// State tracking for RX watchdog and CAN TX
volatile TickType_t last_heartbeat_tick = 0;
volatile uint8_t last_power_value = 0; 
volatile uint8_t global_power_payload = 0; 


// --- I2C HELPER FUNCTIONS ---
static esp_err_t ltc4151_register_read(i2c_master_dev_handle_t dev_handle, uint8_t reg_addr, uint8_t *data, size_t len) 
{
    return i2c_master_transmit_receive(dev_handle, &reg_addr, 1, data, len, I2C_MASTER_TIMEOUT_MS); 
}

static void i2c_master_init(i2c_master_bus_handle_t *bus_handle, i2c_master_dev_handle_t *dev_handle) 
{
    i2c_master_bus_config_t bus_config = { 
        .i2c_port = I2C_MASTER_NUM, 
        .sda_io_num = I2C_MASTER_SDA_IO, 
        .scl_io_num = I2C_MASTER_SCL_IO, 
        .clk_source = I2C_CLK_SRC_DEFAULT, 
        .glitch_ignore_cnt = 7, 
        .flags.enable_internal_pullup = false, 
    };
    ESP_ERROR_CHECK(i2c_new_master_bus(&bus_config, bus_handle)); 

    i2c_device_config_t dev_config = { 
        .dev_addr_length = I2C_ADDR_BIT_LEN_7, 
        .device_address = LTC4151_SENSOR_ADDR, 
        .scl_speed_hz = I2C_MASTER_FREQ_HZ, 
    };
    ESP_ERROR_CHECK(i2c_master_bus_add_device(*bus_handle, &dev_config, dev_handle)); 
}


// --- I2C POWER MONITOR TASK ---
void power_monitor_task(void *arg)
{
    i2c_master_dev_handle_t ltc_handle = (i2c_master_dev_handle_t)arg;
    uint8_t data[2];

    while (1) {
        esp_err_t ret = ltc4151_register_read(ltc_handle, 0x02, data, 2);

        if (ret == ESP_OK) {
            uint16_t raw_adc = (data[0] << 4) | (data[1] >> 4);
            float voltage = raw_adc * 0.025;
            global_power_payload = (uint8_t)(voltage * 10.0);
            ESP_LOGI(TAG, "I2C Read SUCCESS! Local Voltage: %.2f V | Payload Byte: %d", voltage, global_power_payload);
        } else {
            // FAILSAFE: Default to 0 if the sensor read fails
            global_power_payload = 0;
            ESP_LOGE(TAG, "Failed to read I2C sensor. Defaulting to 0V. Error: %s", esp_err_to_name(ret));
        }
        vTaskDelay(pdMS_TO_TICKS(1000)); 
    }
}


// --- TRANSMIT TASKS ---

void pedals_status_task(void *arg) {
    while (1) {
        CAN_message_t tx_msg = {0}; 
        tx_msg.id = 0x01; 
        tx_msg.dlc = 2;   
        tx_msg.data[0] = 0x00; 
        tx_msg.data[1] = global_power_payload; 
        
        CAN_send(&tx_msg, 100); 
        ESP_LOGI(TAG, "TX [0x01] Pedals Status | Heartbeat: 0x00 | Power: %d (%.1f V)", tx_msg.data[1], tx_msg.data[1] / 10.0);
        
        vTaskDelay(pdMS_TO_TICKS(1000)); 
    }
}

void pedal_position_task(void *arg) {
    int raw_adc;
    uint8_t last_logged_position = 0; 

    while (1) {
        ESP_ERROR_CHECK(adc_oneshot_read(adc1_handle, PIN_PEDAL_POT, &raw_adc));
        uint8_t position = (uint8_t)(raw_adc >> 4); 

        CAN_message_t tx_msg = {0};
        tx_msg.id = 0x11; 
        tx_msg.dlc = 1;   
        tx_msg.data[0] = position; 
        
        CAN_send(&tx_msg, 100);

        if (abs(position - last_logged_position) > 2 || 
           (position == 0 && last_logged_position != 0) || 
           (position == 255 && last_logged_position != 255)) {
            
            ESP_LOGI(TAG, "TX [0x11] Pedal Position | Scaled (0-255): %d", position);
            last_logged_position = position;
        }

        vTaskDelay(pdMS_TO_TICKS(50)); 
    }
}

void hazards_btn_task(void *arg) {
    bool last_btn_state = true; 
    bool hazards_on = false;

    while (1) {
        bool current_btn_state = gpio_get_level(PIN_HAZARDS_BTN);

        if (last_btn_state == true && current_btn_state == false) {
            vTaskDelay(pdMS_TO_TICKS(30)); 
            
            if (gpio_get_level(PIN_HAZARDS_BTN) == false) { 
                hazards_on = !hazards_on; 
                
                CAN_message_t tx_msg = {0};
                tx_msg.id = 0x12; 
                tx_msg.dlc = 1;   
                tx_msg.data[0] = hazards_on ? 0x01 : 0x00; 
                
                CAN_send(&tx_msg, 100);
                ESP_LOGW(TAG, "TX [0x12] Hazards Toggled! | Sent: %s (0x%02X)", hazards_on ? "ON" : "OFF", tx_msg.data[0]);
            }
        }
        last_btn_state = current_btn_state;
        vTaskDelay(pdMS_TO_TICKS(10));
    }
}


// --- RECEIVE & LED TASKS ---

void can_rx_task(void *arg) {
    uint8_t rx_throttle = 0; // Throttle counter

    while (1) {
        CAN_message_t rx_msg;
        esp_err_t ret = CAN_receive(&rx_msg, 100);
        
        if (ret == ESP_OK) {
            if (rx_msg.id == 0x02) {
                last_heartbeat_tick = xTaskGetTickCount();
            } 
            else if (rx_msg.id == 0x21) {
                last_power_value = rx_msg.data[0];
                
                // Only log once every 10 received messages (approx 1 second)
                rx_throttle++;
                if (rx_throttle >= 10) {
                    ESP_LOGI(TAG, "RX [0x02] Heartbeat & [0x21] Power Received | Value: %d (%.1f V)", last_power_value, last_power_value / 10.0);
                    rx_throttle = 0;
                }
            }
        }
        vTaskDelay(pdMS_TO_TICKS(10)); 
    }
}

void indicator_led_task(void *arg) {
    bool blink_state = false;
    bool was_warning = false;

    while (1) {
        uint32_t time_since_hb = (xTaskGetTickCount() - last_heartbeat_tick) * portTICK_PERIOD_MS;
        
        if (time_since_hb > 1000) {
            if (!was_warning && last_heartbeat_tick != 0) {
                ESP_LOGE(TAG, "WARNING: Brakelights Heartbeat Timeout! Blinking Indicator LED.");
                was_warning = true;
            }
            blink_state = !blink_state;
            gpio_set_level(PIN_INDICATOR_LED, blink_state);
            vTaskDelay(pdMS_TO_TICKS(250)); 
        } else {
            if (was_warning) {
                ESP_LOGI(TAG, "RESOLVED: Brakelights Heartbeat Restored. Indicator LED Solid.");
                was_warning = false;
            }
            gpio_set_level(PIN_INDICATOR_LED, 1);
            vTaskDelay(pdMS_TO_TICKS(100)); 
        }
    }
}

void rgb_status_led_task(void *arg) {
    bool toggle = false;
    bool last_valid_state = false;

    while (1) {
        toggle = !toggle;
        bool is_valid = (last_power_value >= 100); // 100 = 10.0V

        if (is_valid != last_valid_state) {
            if (is_valid) {
                ESP_LOGI(TAG, "STATE: Power Valid (>=10V). RGB flashing GREEN.");
            } else {
                ESP_LOGW(TAG, "STATE: Power Invalid (<10V). RGB flashing RED.");
            }
            last_valid_state = is_valid;
        }
        
        if (toggle) {
            if (is_valid) {
                led_strip_set_pixel(led_strip, 0, 0, 255, 0); 
            } else {
                led_strip_set_pixel(led_strip, 0, 255, 0, 0); 
            }
            led_strip_refresh(led_strip);
        } else {
            led_strip_clear(led_strip); 
        }
        
        vTaskDelay(pdMS_TO_TICKS(500)); 
    }
}


// --- MAIN ---
void app_main(void) {
    vTaskDelay(pdMS_TO_TICKS(2000));
    ESP_LOGI(TAG, "================================================");
    ESP_LOGI(TAG, "Pedals ESP32 Booting Up...");
    ESP_LOGI(TAG, "================================================");

    // 1. Setup GPIOs
    gpio_set_direction(PIN_HAZARDS_BTN, GPIO_MODE_INPUT);
    gpio_set_pull_mode(PIN_HAZARDS_BTN, GPIO_PULLUP_ONLY);

    gpio_reset_pin(PIN_INDICATOR_LED);
    gpio_set_direction(PIN_INDICATOR_LED, GPIO_MODE_OUTPUT);

    // 2. Configure Addressable RGB LED 
    led_strip_config_t strip_config = {
        .strip_gpio_num = PIN_RGB_LED,
        .max_leds = 1, 
    };
    led_strip_rmt_config_t rmt_config = {
        .resolution_hz = 10 * 1000 * 1000, 
        .flags.with_dma = false,
    };
    ESP_ERROR_CHECK(led_strip_new_rmt_device(&strip_config, &rmt_config, &led_strip));
    led_strip_clear(led_strip);

    // 3. Setup ADC
    adc_oneshot_unit_init_cfg_t init_config1 = { .unit_id = ADC_UNIT_1 };
    ESP_ERROR_CHECK(adc_oneshot_new_unit(&init_config1, &adc1_handle));
    adc_oneshot_chan_cfg_t config = {
        .bitwidth = ADC_BITWIDTH_DEFAULT,
        .atten = ADC_ATTEN_DB_12,
    };
    ESP_ERROR_CHECK(adc_oneshot_config_channel(adc1_handle, PIN_PEDAL_POT, &config));

    // 4. Initialize I2C & CAN
    i2c_master_bus_handle_t bus_handle;
    i2c_master_dev_handle_t ltc_handle;
    i2c_master_init(&bus_handle, &ltc_handle);
    
    ESP_ERROR_CHECK(CAN_init());
    ESP_LOGI(TAG, "Drivers Initialized. Starting pinned tasks...");

    // 5. Start Pinned Tasks
    xTaskCreatePinnedToCore(power_monitor_task, "power_monitor", 4096, (void *)ltc_handle, 2, NULL, 1);
    xTaskCreatePinnedToCore(pedals_status_task, "pedals_status", 4096, NULL, 2, NULL, 1);
    xTaskCreatePinnedToCore(pedal_position_task, "pedal_pos", 4096, NULL, 2, NULL, 1);
    xTaskCreatePinnedToCore(hazards_btn_task, "hazards_btn", 4096, NULL, 3, NULL, 1);
    
    xTaskCreatePinnedToCore(can_rx_task, "can_rx", 4096, NULL, 4, NULL, 1);
    xTaskCreatePinnedToCore(indicator_led_task, "indicator_led", 2048, NULL, 1, NULL, 1);
    xTaskCreatePinnedToCore(rgb_status_led_task, "rgb_led", 2048, NULL, 1, NULL, 1);

    // 6. Keep app_main alive
    while (1) {
        vTaskDelay(pdMS_TO_TICKS(1000)); 
    }
}
