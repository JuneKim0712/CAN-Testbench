#include <stdio.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "unity.h"
#include "esp_log.h"

static const char *TAG = "CALSOL_TB";

// Sample Unit Tests for CalSol CAN Architecture
static void test_can_id_validation(void)
{
    uint32_t bms_id = 0x0B;
    uint32_t steering_id = 0x05;

    // Verify CAN standard 11-bit IDs
    TEST_ASSERT_TRUE(bms_id <= 0x7FF);
    TEST_ASSERT_TRUE(steering_id <= 0x7FF);
    TEST_ASSERT_NOT_EQUAL(bms_id, steering_id);
}

static void test_bms_state_transitions(void)
{
    typedef enum {
        STATE_IDLE = 0,
        STATE_ACTIVE,
        STATE_OVERCHARGE_FAULT
    } bms_state_t;

    bms_state_t current = STATE_IDLE;
    TEST_ASSERT_EQUAL_INT(STATE_IDLE, current);

    // Transition to ACTIVE
    current = STATE_ACTIVE;
    TEST_ASSERT_EQUAL_INT(STATE_ACTIVE, current);

    // Transition to FAULT
    current = STATE_OVERCHARGE_FAULT;
    TEST_ASSERT_EQUAL_INT(STATE_OVERCHARGE_FAULT, current);
}

void app_main(void)
{
    // Wait for USB CDC/JTAG enumeration
    vTaskDelay(pdMS_TO_TICKS(1500));

    ESP_LOGI(TAG, "========================================");
    ESP_LOGI(TAG, "  CalSol CAN Testbench Unity Runner    ");
    ESP_LOGI(TAG, "========================================");

    UNITY_BEGIN();
    RUN_TEST(test_can_id_validation);
    RUN_TEST(test_bms_state_transitions);
    UNITY_END();

    ESP_LOGI(TAG, "Target unit testing sequence finished.");
}
