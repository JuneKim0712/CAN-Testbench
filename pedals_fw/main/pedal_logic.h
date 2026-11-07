#pragma once

#include <stdint.h>
#include <stdbool.h>
#include "CAN.h"

#define CAN_ID_PEDAL_THROTTLE  0x11
#define CAN_ID_PEDAL_HAZARDS   0x12

/**
 * @brief Calculate throttle percent (0 - 100%) from raw 12-bit ADC reading.
 * Deadzone below 500 counts (0%), saturation above 3500 counts (100%).
 */
uint8_t pedal_calculate_throttle(int raw_adc);

/**
 * @brief Safety plausibility interlock check.
 * FSAE/CalSol Rule: Throttle > 25% while brake is active triggers cutoff.
 */
bool pedal_is_plausible(uint8_t throttle_percent, bool brake_engaged);

/**
 * @brief Construct standard CAN message for pedal throttle position.
 */
CAN_message_t pedal_build_throttle_msg(uint8_t throttle_percent);

/**
 * @brief Construct standard CAN message for hazard button toggle state.
 */
CAN_message_t pedal_build_hazards_msg(bool hazards_on);

/**
 * @brief Decode incoming throttle CAN frame.
 * Validates frame is standard, not RTR, matches ID 0x11, and has DLC >= 1.
 */
bool pedal_decode_throttle_msg(const CAN_message_t *msg, uint8_t *out_throttle);
