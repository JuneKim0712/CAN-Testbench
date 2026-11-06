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

// -----------------------------------------------------------------------------
// Test 1: Throttle calculation, deadzone, and saturation limits
// -----------------------------------------------------------------------------
static void test_throttle_calculation_and_deadzone(void)
{
    TEST_ASSERT_EQUAL_UINT8(1, calculate_throttle_percent(0));
    TEST_ASSERT_EQUAL_UINT8(0, calculate_throttle_percent(499));
    TEST_ASSERT_EQUAL_UINT8(0, calculate_throttle_percent(500));
    TEST_ASSERT_EQUAL_UINT8(50, calculate_throttle_percent(2000));
    TEST_ASSERT_EQUAL_UINT8(100, calculate_throttle_percent(3500));
    TEST_ASSERT_EQUAL_UINT8(100, calculate_throttle_percent(4095));
}

// -----------------------------------------------------------------------------
// Test 2: Brake pedal plausibility interlock
// -----------------------------------------------------------------------------
static void test_brake_plausibility_safety_interlock(void)
{
    // Brake not engaged: any throttle valid
    TEST_ASSERT_TRUE(is_throttle_plausible(50, false));
    TEST_ASSERT_TRUE(is_throttle_plausible(100, false));

    // Brake engaged with low throttle (<=25%): valid
    TEST_ASSERT_TRUE(is_throttle_plausible(20, true));
    TEST_ASSERT_TRUE(is_throttle_plausible(25, true));

    // Brake engaged with high throttle (>25%): PLAUSIBILITY CUTOFF
    TEST_ASSERT_FALSE(is_throttle_plausible(26, true));
    TEST_ASSERT_FALSE(is_throttle_plausible(100, true));
}

// -----------------------------------------------------------------------------
// Test 3: CAN packet builder clamping, defaults, and zero-padding
// -----------------------------------------------------------------------------
static void test_can_packet_builder_clamping_and_zeroing(void)
{
    uint8_t sample_data[4] = {0xAA, 0xBB, 0xCC, 0xDD};
    CAN_message_t msg = build_packet_no_ext(0x11, sample_data, 4);

    TEST_ASSERT_EQUAL_HEX32(0x11, msg.id);
    TEST_ASSERT_EQUAL_UINT8(4, msg.dlc);
    TEST_ASSERT_FALSE(msg.extended);
    TEST_ASSERT_FALSE(msg.rtr);
    TEST_ASSERT_EQUAL_HEX8(0xAA, msg.data[0]);
    TEST_ASSERT_EQUAL_HEX8(0xBB, msg.data[1]);
    TEST_ASSERT_EQUAL_HEX8(0xCC, msg.data[2]);
    TEST_ASSERT_EQUAL_HEX8(0xDD, msg.data[3]);
    // Trailing bytes must be zeroed
    TEST_ASSERT_EQUAL_HEX8(0x00, msg.data[4]);
    TEST_ASSERT_EQUAL_HEX8(0x00, msg.data[7]);

    // Clamping test: dlc > 8 must clamp to 8
    CAN_message_t clamped = build_packet_no_ext(0x22, sample_data, 12);
    TEST_ASSERT_EQUAL_UINT8(8, clamped.dlc);

    // Default test: dlc == 0 defaults to 8
    CAN_message_t def = build_packet_no_ext(0x33, sample_data, 0);
    TEST_ASSERT_EQUAL_UINT8(8, def.dlc);
}

// -----------------------------------------------------------------------------
// Test 4: CAN driver hardware lifecycle (init, duplicate init, deinit)
// -----------------------------------------------------------------------------
static void test_can_driver_lifecycle(void)
{
    // Ensure clean initial state
    CAN_deinit();

    // 1. Initial init must succeed
    esp_err_t err = CAN_init();
    TEST_ASSERT_EQUAL(ESP_OK, err);

    // 2. Duplicate init must fail safely with ESP_ERR_INVALID_STATE
    err = CAN_init();
    TEST_ASSERT_EQUAL(ESP_ERR_INVALID_STATE, err);

    // 3. Deinit must succeed
    err = CAN_deinit();
    TEST_ASSERT_EQUAL(ESP_OK, err);

    // 4. Duplicate deinit must fail safely with ESP_ERR_INVALID_STATE
    err = CAN_deinit();
    TEST_ASSERT_EQUAL(ESP_ERR_INVALID_STATE, err);
}

// -----------------------------------------------------------------------------
// Test 5: CAN driver uninitialized error safety
// -----------------------------------------------------------------------------
static void test_can_driver_uninitialized_safety(void)
{
    // Ensure driver is deinitialized
    CAN_deinit();

    CAN_message_t msg = {0};
    msg.id = 0x11;
    msg.dlc = 1;

    // Send while deinitialized must return ESP_ERR_INVALID_STATE
    TEST_ASSERT_EQUAL(ESP_ERR_INVALID_STATE, CAN_send(&msg, 10));

    // Receive while deinitialized must return ESP_ERR_INVALID_STATE
    TEST_ASSERT_EQUAL(ESP_ERR_INVALID_STATE, CAN_receive(&msg, 10));

    // Receive with NULL pointer must return ESP_ERR_INVALID_ARG
    // Re-init temporarily to test NULL pointer guard
    CAN_init();
    TEST_ASSERT_EQUAL(ESP_ERR_INVALID_ARG, CAN_receive(NULL, 10));
    CAN_deinit();
}

// -----------------------------------------------------------------------------
// Test 6: CAN receive timeout behavior
// -----------------------------------------------------------------------------
static void test_can_receive_timeout(void)
{
    CAN_deinit();
    TEST_ASSERT_EQUAL(ESP_OK, CAN_init());

    CAN_message_t rx_msg = {0};
    // Expect timeout after 50ms when bus has no inbound frames
    esp_err_t err = CAN_receive(&rx_msg, 50);
    TEST_ASSERT_EQUAL(ESP_ERR_TIMEOUT, err);

    CAN_deinit();
}

// -----------------------------------------------------------------------------
// Test 7: Pedal CAN frame transmission
// -----------------------------------------------------------------------------
static void test_pedal_can_transmission(void)
{
    CAN_deinit();
    TEST_ASSERT_EQUAL(ESP_OK, CAN_init());

    // Compute throttle at 2000 ADC (50%)
    uint8_t throttle = calculate_throttle_percent(2000);
    TEST_ASSERT_EQUAL_UINT8(50, throttle);

    CAN_message_t pedal_msg = build_packet_no_ext(0x11, &throttle, 1);
    TEST_ASSERT_EQUAL_HEX32(0x11, pedal_msg.id);
    TEST_ASSERT_EQUAL_UINT8(1, pedal_msg.dlc);
    TEST_ASSERT_EQUAL_UINT8(50, pedal_msg.data[0]);

    // Transmit frame over physical bus
    esp_err_t err = CAN_send(&pedal_msg, 100);
    TEST_ASSERT_EQUAL(ESP_OK, err);

    CAN_deinit();
}

// -----------------------------------------------------------------------------
// Application Entrypoint
// -----------------------------------------------------------------------------
void app_main(void)
{
    vTaskDelay(pdMS_TO_TICKS(1500));

    ESP_LOGI(TAG, "========================================");
    ESP_LOGI(TAG, "  CalSol Gen11: Pedals & CAN Unit Tests  ");
    ESP_LOGI(TAG, "========================================");

    UNITY_BEGIN();
    RUN_TEST(test_throttle_calculation_and_deadzone);
    RUN_TEST(test_brake_plausibility_safety_interlock);
    RUN_TEST(test_can_packet_builder_clamping_and_zeroing);
    RUN_TEST(test_can_driver_lifecycle);
    RUN_TEST(test_can_driver_uninitialized_safety);
    RUN_TEST(test_can_receive_timeout);
    RUN_TEST(test_pedal_can_transmission);
    UNITY_END();

    ESP_LOGI(TAG, "Pedals & CAN unit tests completed.");
}
