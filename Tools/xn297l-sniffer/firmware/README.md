# XN297L sniffer – Firmware

Zephyr application for the **nRF52840 MDK USB Dongle** (makerdiary). It uses no Bluetooth stack:
the `RADIO` peripheral is programmed directly as a raw GFSK receiver that synchronises on an
XN297L sync word and reports the captured bytes as text lines over USB CDC.
Usage, command set, flashing and building: [../README.md](../README.md).

## Contents

| Path | Content |
|---|---|
| `CMakeLists.txt` | Zephyr build file (`west build -b nrf52840_mdk_usb_dongle firmware`) |
| `prj.conf` | Kconfig: USB CDC ACM, no Bluetooth stack, no logging/console on the data port, UF2 output |
| [boards/](boards/README.md) | devicetree overlay for the dongle (CDC ACM UART) |
| [src/](src/README.md) | C sources: command parser and main loop, raw RADIO driver |
| [prebuilt/](prebuilt/README.md) | ready-to-flash `.uf2` built from this source |

## Build

```bash
# inside a west workspace (nRF Connect SDK or plain Zephyr), tested with Zephyr v3.7.0 / SDK 0.16.8
west build -b nrf52840_mdk_usb_dongle -p always path/to/Tools/xn297l-sniffer/firmware
# result: build/zephyr/zephyr.uf2
```
