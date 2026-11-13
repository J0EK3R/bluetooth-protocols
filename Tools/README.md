# Tools

Capture tools used to verify the protocols in this repository. Both run on the
**nRF52840 MDK USB Dongle** (makerdiary) and can be swapped by drag and drop (UF2 bootloader).
Overview: [../README.md](../README.md).

## Contents

| Folder | Content |
|---|---|
| [nrf-sniffer-ble/](nrf-sniffer-ble/README.md) | nRF Sniffer for Bluetooth LE: firmware backup and installation of the Wireshark capture tool – for BLE advertising and GATT connections (e.g. [MKH4.0](../MouldKing/MKH4.0.md)) |
| [xn297l-sniffer/](xn297l-sniffer/README.md) | XN297L sniffer: own Zephyr firmware, Wireshark extcap and Lua dissector – receives raw XN297L frames (e.g. from original remote controls) and decodes address, payload and CRC |
