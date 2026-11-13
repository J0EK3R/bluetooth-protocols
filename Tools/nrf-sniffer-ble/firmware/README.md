# nRF Sniffer for Bluetooth LE – Firmware backup

Firmware read back from the nRF52840 MDK USB Dongle. Restore and installation instructions:
[../README.md](../README.md).

| File | Content |
|---|---|
| `nrf_sniffer_ble_4.1.1_nrf52840_mdk_usb_dongle.uf2` | `CURRENT.UF2` read back from the dongle: nRF Sniffer for Bluetooth LE 4.1.1, flash range `0x1000` … `0x12000`, no SoftDevice |
| `INFO_UF2.TXT` | bootloader information of the dongle the backup was taken from (UF2 Bootloader 0.2.13, Board-ID `nRF52840-Dongle-v1`) |

To restore: press the dongle button twice quickly (drive **UF2BOOT** appears) and copy the
`.uf2` file onto the drive.
