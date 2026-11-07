#pragma once
#include "CAN.h"

// Example application contract: replace with your ECU's actual protocol.
#define EXAMPLE_COMMAND_ID 0x600
#define EXAMPLE_REQUEST_ID 0x601

typedef struct {
    uint8_t demand;
} command_state_t;

bool handle_command(command_state_t *state, const CAN_message_t *message);
