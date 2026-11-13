# XN297L sniffer – Prebuilt firmware

Ready-to-flash firmware, built from [../](../README.md) (Zephyr 3.7.0, SDK 0.16.8).

| File | Content |
|---|---|
| `xn297l_sniffer_nrf52840_mdk_usb_dongle.uf2` | UF2 image for the nRF52840 MDK USB Dongle, application at `0x1000` (same start address as the nRF Sniffer for Bluetooth LE) |

To flash: press the dongle button twice quickly (drive **UF2BOOT** appears) and copy the `.uf2`
file onto the drive. Details: [../../README.md](../../README.md).
