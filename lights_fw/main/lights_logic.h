#pragma once
#include <stdint.h>
typedef enum { STATE_IDLE = 0, STATE_ACTIVE } system_state_t;
float calculate_sensor_voltage(uint16_t raw_adc);
system_state_t transition_state(system_state_t current);
