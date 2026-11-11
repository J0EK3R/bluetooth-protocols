# nRF Sniffer for Bluetooth LE (nRF52840 MDK USB Dongle)

> Backup of the BLE sniffer firmware running on the nRF52840 MDK USB Dongle, plus notes on
> installing the Wireshark capture tool.
> Last updated: 2026-11-11

The [nRF Sniffer for Bluetooth LE](https://infocenter.nordicsemi.com/topic/ug_sniffer_ble/UG/sniffer_ble/installing_sniffer.html)
(Nordic Semiconductor) turns the dongle into a BLE sniffer for Wireshark. It captures
advertising packets and can follow connections. This makes it the right tool for BLE
advertising based devices and for GATT devices such as the [MKH4.0](../../MouldKing/MKH4.0.md).

It cannot receive raw XN297L frames, for example from original remote controls. For those,
use the [XN297L sniffer](../xn297l-sniffer/README.md), which runs on the same dongle.

---

## 1. Firmware backup

| File | Content |
|---|---|
| `firmware/nrf_sniffer_ble_4.1.1_nrf52840_mdk_usb_dongle.uf2` | `CURRENT.UF2` read back from the dongle (application flash) |
| `firmware/INFO_UF2.TXT` | bootloader information of the dongle the backup was taken from |

Details of the backup (analysed from the UF2 blocks):

| Property | Value |
|---|---|
| Application | nRF Sniffer for Bluetooth LE, version string `4.1.1` found in the image |
| Flash range | `0x1000` … `0x12000` (68 KiB), contiguous, directly after the Nordic MBR |
| SoftDevice | none: the application starts at `0x1000` |
| UF2 family ID | `0xADA52840` (nRF52840) |
| Bootloader | UF2 Bootloader 0.2.13-42-g82464f9-dirty, Board-ID `nRF52840-Dongle-v1`, built Feb 3 2020 |

The XN297L sniffer firmware uses the same start address (`0x1000`), so both firmwares can be
swapped at any time by drag and drop.

## 2. Restoring the firmware

1. With the dongle plugged in, press the button **twice quickly**. The RGB LED turns green and the
   drive **UF2BOOT** appears. (Tested with UF2 bootloader 0.2.13; according to the makerdiary
   documentation, newer bootloaders enter this mode by holding the button while plugging the
   dongle in.)
2. Copy `firmware/nrf_sniffer_ble_4.1.1_nrf52840_mdk_usb_dongle.uf2` onto the drive.
3. The dongle restarts as nRF Sniffer (serial port).

## 3. Installing the Wireshark capture tool

The capture tool (extcap) comes from Nordic's *nRF Sniffer for Bluetooth LE* package, which must
match the firmware version (4.1.x). The steps follow the
[makerdiary installation guide](https://wiki.makerdiary.com/nrf52840-mdk-usb-dongle/guides/ble-sniffer/installation/#installing-the-nrf-sniffer-capture-tool):

1. Download and unpack the nRF Sniffer for Bluetooth LE package (version 4.1.x).
2. Install the Python requirements:
   ```bash
   cd <package>/extcap
   python -m pip install -r requirements.txt
   ```
3. Copy the **contents** of `<package>/extcap` into Wireshark's personal extcap folder
   (*Help → About Wireshark → Folders → Personal Extcap path*, on Windows usually
   `%APPDATA%\Wireshark\extcap`).
4. Optional: copy the Wireshark profile from `<package>/Profile_nRF_Sniffer_Bluetooth_LE` into the
   personal profiles folder.
5. Restart Wireshark or refresh the interfaces (F5). Enable *View → Interface Toolbars → nRF
   Sniffer for Bluetooth LE* and start capturing on **nRF Sniffer for Bluetooth LE COMx**.

The XN297L sniffer extcap can be installed in the same folder; Wireshark then lists both interfaces.

## 4. License

The nRF Sniffer firmware is © Nordic Semiconductor ASA. It is stored here only as a backup of the
dongle's firmware. Its use is subject to Nordic's license terms, which allow redistribution in binary form
only for use with Nordic Semiconductor devices.

## Open questions

- Is the backup complete, i.e. does `CURRENT.UF2` contain the whole application or only the range
  recorded by the bootloader? Restoring has not been tested yet.
