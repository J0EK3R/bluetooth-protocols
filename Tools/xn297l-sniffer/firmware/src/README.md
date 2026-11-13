# XN297L sniffer – Firmware sources

C sources of the sniffer firmware. Back to the firmware: [../README.md](../README.md).
All byte values are in **on-air order, MSB first**, the same notation as in
[Chips/XN297L.md](../../../../Chips/XN297L.md).

| File | Content |
|---|---|
| `main.c` | USB CDC setup, line-based ASCII command parser (`help`, `info`, `sync`, `len`, `ch`, `dwell`, `rate`, `start`, `stop`), channel hopping, packet reports to the host, LEDs |
| `radio.h` | API of the raw receiver: limits (sync word 3 … 5 bytes, up to 250 captured bytes), configuration and receive functions |
| `radio.c` | raw receiver on top of the nRF52840 `RADIO` peripheral: maps the sync word to `BASE0`/`PREFIX0`, switches hardware CRC and whitening off, data rates `nrf1m` / `ble1m` / `nrf2m` |
