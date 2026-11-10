#include "lights_logic.h"
float calculate_sensor_voltage(uint16_t raw_adc) { return raw_adc * 0.025f; }
system_state_t transition_state(system_state_t current)
{
    return current == STATE_IDLE ? STATE_ACTIVE : STATE_IDLE;
}
