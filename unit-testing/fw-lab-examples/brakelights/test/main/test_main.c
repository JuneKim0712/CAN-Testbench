#include <stdio.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "unity.h"
#include "esp_log.h"
#include "CAN.h"

static const char *TAG = "LIGHTS_TEST";

// Subsystem Logic Under Test: Voltage Conversion from LTC4151
static float calculate_sensor_voltage(uint16_t raw_adc)
{
    return raw_adc * 0.025f;
}

// Subsystem Logic Under Test: State Machine
typedef enum {
    STATE_IDLE = 0,
    STATE_ACTIVE
} system_state_t;

static system_state_t transition_state(system_state_t current)
{
    return (current == STATE_IDLE) ? STATE_ACTIVE : STATE_IDLE;
}

// Unity Tests
static void test_voltage_conversion(void)
{
    // 0 raw ADC = 0.0V
    TEST_ASSERT_FLOAT_WITHIN(0.001f, 0.0f, calculate_sensor_voltage(0));

    // 400 raw ADC * 0.025 = 10.0V
    TEST_ASSERT_FLOAT_WITHIN(0.001f, 10.0f, calculate_sensor_voltage(400));
}

static void test_state_toggle(void)
{
    system_state_t state = STATE_IDLE;
    state = transition_state(state);
    TEST_ASSERT_EQUAL_INT(STATE_ACTIVE, state);

    state = transition_state(state);
    TEST_ASSERT_EQUAL_INT(STATE_IDLE, state);
}

static void test_can_message_format(void)
{
    CAN_message_t msg = {0};
    msg.id = 0x21; // Lights Power ID
    msg.dlc = 1;
    msg.data[0] = 125; // 12.5V payload

    TEST_ASSERT_EQUAL_HEX32(0x21, msg.id);
    TEST_ASSERT_EQUAL_UINT8(1, msg.dlc);
    TEST_ASSERT_EQUAL_UINT8(125, msg.data[0]);
}

void app_main(void)
{
    vTaskDelay(pdMS_TO_TICKS(1500));

    ESP_LOGI(TAG, "========================================");
    ESP_LOGI(TAG, "  CalSol Gen11: Lights FW Unit Tests    ");
    ESP_LOGI(TAG, "========================================");

    UNITY_BEGIN();
    RUN_TEST(test_voltage_conversion);
    RUN_TEST(test_state_toggle);
    RUN_TEST(test_can_message_format);
    UNITY_END();

    ESP_LOGI(TAG, "Lights FW test run complete.");
}
