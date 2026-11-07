#include "message_handler.h"

bool handle_command(command_state_t *state, const CAN_message_t *message)
{
    if (state == NULL || message == NULL || message->extended || message->rtr ||
        message->id != EXAMPLE_COMMAND_ID || message->dlc != 1 ||
        message->data[0] > 100) {
        return false;
    }
    state->demand = message->data[0];
    return true;
}
