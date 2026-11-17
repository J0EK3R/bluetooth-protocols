# SPDX-License-Identifier: Apache-2.0
#
# XN297L sniffer firmware for the nRF52840 MDK USB Dongle.
# Build:  west build -b nrf52840_mdk_usb_dongle firmware
#
# The application is a plain Zephyr application without Bluetooth stack:
# the RADIO peripheral is programmed directly as a raw 1 Mbps GFSK receiver (XN297L mode) or as a BLE receiver (BLE mode).

cmake_minimum_required(VERSION 3.20.0)

# Pull in Zephyr (ZEPHYR_BASE is set by west or the nRF Connect SDK)
find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})

project(xn297l_sniffer)

# Application sources
target_sources(app PRIVATE
    src/main.c      # command parser, main loop, USB CDC output
    src/radio.c     # raw RADIO configuration and packet reception (XN297L backend)
    src/ble_radio.c # Bluetooth LE receiver: RADIO, TIMER, PPI, interrupts (BLE backend)
    src/ble_follow.c # connection following logic (pure C, host testable)
    src/ble_pdu.c   # CONNECT_IND / LL control PDU parsing (pure C)
    src/ble_csa.c   # channel selection algorithms #1 and #2 (pure C)
    src/out.c       # ring buffered text output to the USB CDC port
)
