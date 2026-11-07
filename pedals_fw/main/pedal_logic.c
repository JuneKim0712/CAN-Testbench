#include "pedal_logic.h"

uint8_t pedal_calculate_throttle(int raw_adc)
{
    // Deadzone below 500
    if (raw_adc <= 500) return 0;
    // Saturation above 3500
    if (raw_adc >= 3500) return 100;

    return (uint8_t)(((raw_adc - 500) * 100) / 3000);
}

bool pedal_is_plausible(uint8_t throttle_percent, bool brake_engaged)
{
    // FSAE/CalSol Rule: Throttle > 25% while brake is active must trigger cutoff
    if (brake_engaged && throttle_percent > 25) {
        return false;
    }
    return true;
}

CAN_message_t pedal_build_throttle_msg(uint8_t throttle_percent)
{
    CAN_message_t msg = {0};
    msg.id       = CAN_ID_PEDAL_THROTTLE;
    msg.dlc      = 1;
    msg.data[0]  = throttle_percent;
    msg.extended = false;
    msg.rtr      = false;
    return msg;
}

CAN_message_t pedal_build_hazards_msg(bool hazards_on)
{
    CAN_message_t msg = {0};
    msg.id       = CAN_ID_PEDAL_HAZARDS;
    msg.dlc      = 1;
    msg.data[0]  = hazards_on ? 0x01 : 0x00;
    msg.extended = false;
    msg.rtr      = false;
    return msg;
}

bool pedal_decode_throttle_msg(const CAN_message_t *msg, uint8_t *out_throttle)
{
    if (msg == NULL || out_throttle == NULL) return false;
    if (msg->extended || msg->rtr) return false;
    if (msg->id != CAN_ID_PEDAL_THROTTLE) return false;
    if (msg->dlc < 1) return false;

    *out_throttle = msg->data[0];
    return true;
}
