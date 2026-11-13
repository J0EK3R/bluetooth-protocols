# XN297L sniffer – Board overlays

Devicetree overlays, picked up automatically by Zephyr for the matching board.
Back to the firmware: [../README.md](../README.md).

| File | Content |
|---|---|
| `nrf52840_mdk_usb_dongle.overlay` | adds a CDC ACM UART (`cdc_acm_uart0`) on the USB device controller; the firmware talks to the host exclusively through this virtual COM port |
