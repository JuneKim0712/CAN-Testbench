#include "unity.h"
#include "sdkconfig.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "message_handler.h"

static command_state_t state;
static bool can_started;

// Explicit DLC preserves zero-length frames; no packet-builder defaults.
static CAN_message_t spoof_command(uint8_t value)
{
    CAN_message_t message = {
        .id = EXAMPLE_COMMAND_ID, .dlc = 1, .data = {value},
        .extended = false, .rtr = false
    };
    return message;
}

void setUp(void)
{
    state = (command_state_t){0};
    can_started = false;
}

void tearDown(void)
{
    // Unity invokes tearDown even after a failed test assertion.
    if (can_started) {
        TEST_ASSERT_EQUAL(ESP_OK, CAN_deinit());
        can_started = false;
    }
}

static void test_inject_valid_command(void)
{
    CAN_message_t message = spoof_command(50);
    TEST_ASSERT_TRUE(handle_command(&state, &message));
    TEST_ASSERT_EQUAL_UINT8(50, state.demand);
}

static void test_command_boundaries(void)
{
    CAN_message_t message = spoof_command(0);
    TEST_ASSERT_TRUE(handle_command(&state, &message));
    TEST_ASSERT_EQUAL_UINT8(0, state.demand);
    message.data[0] = 100;
    TEST_ASSERT_TRUE(handle_command(&state, &message));
    TEST_ASSERT_EQUAL_UINT8(100, state.demand);
}

static void test_reject_malformed_commands(void)
{
    state.demand = 25;
    CAN_message_t message = spoof_command(101);
    TEST_ASSERT_FALSE(handle_command(&state, &message));
    message = spoof_command(50);
    message.dlc = 0;
    TEST_ASSERT_FALSE(handle_command(&state, &message));
    message.dlc = 2;
    TEST_ASSERT_FALSE(handle_command(&state, &message));
    message = spoof_command(50);
    message.id++;
    TEST_ASSERT_FALSE(handle_command(&state, &message));
    message = spoof_command(50);
    message.rtr = true;
    TEST_ASSERT_FALSE(handle_command(&state, &message));
    message.rtr = false;
    message.extended = true;
    TEST_ASSERT_FALSE(handle_command(&state, &message));
    TEST_ASSERT_FALSE(handle_command(&state, NULL));
    TEST_ASSERT_EQUAL_UINT8(25, state.demand);
}

#ifdef CONFIG_CAN_TEST_PHYSICAL_RX
static void test_physical_injection(void)
{
    TEST_ASSERT_EQUAL(ESP_OK, CAN_init());
    can_started = true;

    // Drain a bounded number of old frames; never loop forever on a busy bus.
    CAN_message_t incoming;
    for (unsigned i = 0; i < 16; ++i) {
        if (CAN_receive(&incoming, 0) != ESP_OK) break;
    }

    // Host responds only after observing this request on the physical bus.
    const CAN_message_t request = {
        .id = EXAMPLE_REQUEST_ID, .dlc = 1, .data = {0xA5}
    };
    TEST_ASSERT_EQUAL(ESP_OK, CAN_send(&request, 100));

    const TickType_t start = xTaskGetTickCount();
    while ((xTaskGetTickCount() - start) < pdMS_TO_TICKS(2000)) {
        if (CAN_receive(&incoming, 20) != ESP_OK) continue;
        if (!handle_command(&state, &incoming)) continue;
        TEST_ASSERT_EQUAL_UINT8(50, state.demand);
        return;
    }
    TEST_FAIL_MESSAGE("No valid injected command within 2 seconds");
}
#endif

void app_main(void)
{
    vTaskDelay(pdMS_TO_TICKS(1500));
    UNITY_BEGIN();
    RUN_TEST(test_inject_valid_command);
    RUN_TEST(test_command_boundaries);
    RUN_TEST(test_reject_malformed_commands);
#ifdef CONFIG_CAN_TEST_PHYSICAL_RX
    RUN_TEST(test_physical_injection);
#endif
    UNITY_END();
}
