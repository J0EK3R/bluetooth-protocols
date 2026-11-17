# XN297L sniffer – Prebuilt firmware

Ready-to-flash firmware **2.1.0** (XN297L sniffer + BLE sniffer with connection following, 95232 bytes), built from [../](../README.md) (Zephyr 3.7.0, SDK 0.16.8).
Version 2.0.0 (BLE advertising scan only, 86016 bytes) and 1.1.0 (XN297L only, 80896 bytes) are available in the git history.

| File | Content |
|---|---|
| `xn297l_sniffer_nrf52840_mdk_usb_dongle.uf2` | UF2 image for the nRF52840 MDK USB Dongle, application at `0x1000` (same start address as the nRF Sniffer for Bluetooth LE) |

To flash: with the dongle plugged in, press the button once (drive **UF2BOOT** appears) and copy the `.uf2`
file onto the drive. Details: [../../README.md](../../README.md).
