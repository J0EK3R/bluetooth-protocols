# XN297L sniffer – Firmware sources

C sources of the sniffer firmware. Back to the firmware: [../README.md](../README.md).
All byte values are in **on-air order, MSB first**, the same notation as in
[Chips/XN297L.md](../../../../Chips/XN297L.md).

| File | Content |
|---|---|
| `main.c` | USB CDC setup, line-based ASCII command parser (`help`, `info`, `sync`, `len`, `ch`, `dwell`, `rate`, `start`, `stop`, `mode`, `bch`, `bdwell`, `brssi`, `badv`), channel hopping, packet reports to the host, LEDs |
| `radio.h` | API of the raw receiver: limits (sync word 3 … 5 bytes, up to 250 captured bytes), configuration and receive functions |
| `radio.c` | raw receiver on top of the nRF52840 `RADIO` peripheral: maps the sync word to `BASE0`/`PREFIX0`, switches hardware CRC and whitening off, data rates `nrf1m` / `ble1m` / `nrf2m` |
| `out.h`, `out.c` | text output to the host through a ring buffer drained with `uart_fifo_fill()`: producers never block on USB, a full ring drops whole lines (counted, reported as `I drop n=...`) |
| `ble_radio.h`, `ble_radio.c` | Bluetooth LE receiver (backend `ble`): RADIO in BLE mode with the advertising access address, hardware whitening / CRC-24, interrupt driven receive loop (RADIO interrupt), advertising channel hopping (TIMER3 compare interrupt), 1 MHz time stamps captured by PPI at the access address, 16 slot packet queue for the main loop |
