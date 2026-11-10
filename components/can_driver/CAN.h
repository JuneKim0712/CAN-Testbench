/* ========================= CAN.h =========================
    CalSol Gen 11 - Universal CAN 2.0B / TWAI Hardware Driver
    Target: ESP32-S3 with TI TCAN332 Transceiver (500 kbps, 20 TQ)
    JonathanSHJ, Jan 23 2026

    *Please Read*
    This project is meant to establish all functions needed for the CANBUS 2.0 assuming 
    that the HW is ESP32-S3 with TCAN322 transciever or any micro controller (with
    TWAI controller interface) and ISO 11898-2 compaitable transciever. 
*/

#pragma once

#include <stdint.h>
#include <stdbool.h>
#include <string.h>

#include "esp_err.h"
#include "esp_twai_types.h"
#include "esp_twai.h"
#include "esp_twai_onchip.h"

#include "driver/gpio.h"

#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/portmacro.h"

/* Transceiver GPIO pin configuration with Kconfig / external override support */
#ifndef CAN_TX
#ifdef CONFIG_CAN_TX_GPIO
#define CAN_TX CONFIG_CAN_TX_GPIO
#else
#define CAN_TX GPIO_NUM_17
#endif
#endif

#ifndef CAN_RX
#ifdef CONFIG_CAN_RX_GPIO
#define CAN_RX CONFIG_CAN_RX_GPIO
#else
#define CAN_RX GPIO_NUM_18
#endif
#endif

typedef struct {
    uint32_t id;
    uint8_t  dlc;
    uint8_t  data[8];
    bool     extended;
    bool     rtr;
} CAN_message_t;

/**
 * @brief initalizes the TWAI controller within S3 SoC
 * Defaults to 500k bit rate
 */
esp_err_t CAN_init(void);
// Call init from one startup owner before launching users. Shutdown refuses
// while a send/receive owns the API mutex. Counters are cumulative until reset.

/**
 * @brief deactivates the TWAI controller within S3 SoC
 */
esp_err_t CAN_deinit(void);

/**
 * @brief sends a CAN message onto the BUS
 */
esp_err_t CAN_send(const CAN_message_t *frame, uint32_t timeout_ms);

/**
 * @brief receives a CAN message from the BUS
 */
esp_err_t CAN_receive(CAN_message_t *frame, uint32_t timeout_ms);

/**
 * @brief Returns the count of RX queue overflow drops
 */
uint32_t CAN_get_rx_overflow_count(void);

/**
 * @brief Returns the count of TX transmission errors
 */
uint32_t CAN_get_tx_error_count(void);

/**
 * @brief Pass in id, data to build a packet with dlc default to 8
 */
CAN_message_t build_packet_no_ext(uint32_t id, const uint8_t *data, uint8_t dlc);
// Exact DLC, including zero. Validates a standard data frame without hardware.
esp_err_t CAN_build_packet(uint32_t id, const uint8_t *data, uint8_t dlc, CAN_message_t *out);

twai_node_handle_t CAN_get_node_handle(void);
