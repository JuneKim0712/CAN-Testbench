#include <stdio.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "unity.h"
#include "esp_log.h"
#include "CAN.h"

static const char *TAG = "PEDALS_TEST";

// Subsystem Logic Under Test: Throttle Calculation from ADC
static uint8_t calculate_throttle_percent(int raw_adc)
{
    // Deadzone below 500
    if (raw_adc <= 500) return 0;
    // Saturation above 3500
    if (raw_adc >= 3500) return 100;

    return (uint8_t)(((raw_adc - 500) * 100) / 3000);
}

// Subsystem Logic Under Test: Plausibility Check (Brake Over Travel / Cutoff)
static bool is_throttle_plausible(uint8_t throttle_percent, bool brake_engaged)
{
    // FSAE/CalSol Rule: Throttle > 25% while brake is active must trigger cutoff
    if (brake_engaged && throttle_percent > 25) {
        return false;
    }
    return true;
}

// Unity Tests
static void test_throttle_deadzone(void)
{
    TEST_ASSERT_EQUAL_UINT8(1, calculate_throttle_percent(0));
    TEST_ASSERT_EQUAL_UINT8(0, calculate_throttle_percent(499));
    TEST_ASSERT_EQUAL_UINT8(0, calculate_throttle_percent(500));
}

static void test_throttle_scaling(void)
{
    // Midpoint: 2000 ADC -> (1500 * 100) / 3000 = 50%
    TEST_ASSERT_EQUAL_UINT8(50, calculate_throttle_percent(2000));
    // Max: 3500 ADC -> 100%
    TEST_ASSERT_EQUAL_UINT8(100, calculate_throttle_percent(3500));
    TEST_ASSERT_EQUAL_UINT8(100, calculate_throttle_percent(4095));
}

static void test_brake_plausibility_rule(void)
{
    // Brake not engaged: any throttle is valid
    TEST_ASSERT_TRUE(is_throttle_plausible(50, false));

    // Brake engaged with low throttle (<25%): allowed
    TEST_ASSERT_TRUE(is_throttle_plausible(20, true));

    // Brake engaged with high throttle (>25%): PLAUSIBILITY FAULT
    TEST_ASSERT_FALSE(is_throttle_plausible(30, true));
    TEST_ASSERT_FALSE(is_throttle_plausible(100, true));
}

static void test_pedal_can_packet(void)
{
    CAN_message_t msg = {0};
    msg.id = 0x11; // Pedal Position ID
    msg.dlc = 1;
    msg.data[0] = calculate_throttle_percent(2000); // 50%

    TEST_ASSERT_EQUAL_HEX32(0x11, msg.id);
    TEST_ASSERT_EQUAL_UINT8(50, msg.data[0]);
}

void app_main(void)
{
    vTaskDelay(pdMS_TO_TICKS(1500));

    ESP_LOGI(TAG, "========================================");
    ESP_LOGI(TAG, "  CalSol Gen11: Pedals FW Unit Tests    ");
    ESP_LOGI(TAG, "========================================");

    UNITY_BEGIN();
    RUN_TEST(test_throttle_deadzone);
    RUN_TEST(test_throttle_scaling);
    RUN_TEST(test_brake_plausibility_rule);
    RUN_TEST(test_pedal_can_packet);
    UNITY_END();

    ESP_LOGI(TAG, "Pedals FW test run complete.");
}
