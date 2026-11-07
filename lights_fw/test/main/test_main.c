#include <stdio.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "unity.h"
#include "esp_log.h"
#include "CAN.h"

static const char *TAG = "LIGHTS_TEST";

#include "lights_logic.h"

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

static void test_exact_packet_builder(void)
{
    CAN_message_t message;
    TEST_ASSERT_EQUAL(ESP_OK, CAN_build_packet(0x7FF, NULL, 0, &message));
    TEST_ASSERT_EQUAL_UINT8(0, message.dlc);
    uint8_t data[8] = {0, 1, 2, 3, 4, 5, 6, 7};
    TEST_ASSERT_EQUAL(ESP_OK, CAN_build_packet(0, data, 8, &message));
    TEST_ASSERT_EQUAL_UINT8_ARRAY(data, message.data, 8);
    TEST_ASSERT_EQUAL(ESP_ERR_INVALID_ARG, CAN_build_packet(0x800, data, 8, &message));
    TEST_ASSERT_EQUAL(ESP_ERR_INVALID_ARG, CAN_build_packet(0, NULL, 1, &message));
    TEST_ASSERT_EQUAL(ESP_ERR_INVALID_ARG, CAN_build_packet(0, data, 9, &message));
}

static void test_can_heartbeat_transmission(void)
{
    CAN_deinit();
    TEST_ASSERT_EQUAL(ESP_OK, CAN_init());

    // Transmit exactly 10 heartbeat frames onto physical CAN bus
    for (int i = 0; i < 10; i++) {
        CAN_message_t hb_msg = {0};
        hb_msg.id = 0x02; // Lights Subsystem Heartbeat ID
        hb_msg.dlc = 1;
        hb_msg.data[0] = (uint8_t)(i + 1); // Sequence token 1..10
        esp_err_t err = CAN_send(&hb_msg, 50);
        TEST_ASSERT_EQUAL(ESP_OK, err);
        vTaskDelay(pdMS_TO_TICKS(50));
    }

    vTaskDelay(pdMS_TO_TICKS(100));
    TEST_ASSERT_EQUAL(ESP_OK, CAN_deinit());
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
    RUN_TEST(test_exact_packet_builder);
    RUN_TEST(test_can_heartbeat_transmission);
    UNITY_END();

    ESP_LOGI(TAG, "Lights FW test run complete.");
}
