# XN297L sniffer – Firmware sources

C sources of the sniffer firmware. Back to the firmware: [../README.md](../README.md).
All byte values are in **on-air order, MSB first**, the same notation as in
[Chips/XN297L.md](../../../../Chips/XN297L.md).

| File | Content |
|---|---|
| `main.c` | USB CDC setup, line-based ASCII command parser (`help`, `info`, `sync`, `len`, `ch`, `dwell`, `rate`, `start`, `stop`, `mode`, `bch`, `bdwell`, `brssi`, `badv`, `bfollow`, `bconn`, `brsp`), channel hopping, packet reports to the host, LEDs |
| `radio.h` | API of the raw receiver: limits (sync word 3 … 5 bytes, up to 250 captured bytes), configuration and receive functions |
| `radio.c` | raw receiver on top of the nRF52840 `RADIO` peripheral: maps the sync word to `BASE0`/`PREFIX0`, switches hardware CRC and whitening off, data rates `nrf1m` / `ble1m` / `nrf2m` |
| `out.h`, `out.c` | text output to the host through a ring buffer drained with `uart_fifo_fill()`: producers never block on USB, a full ring drops whole lines (counted, reported as `I drop n=...`) |
| `ble_radio.h`, `ble_radio.c` | Bluetooth LE receiver (backend `ble`): RADIO in BLE mode with the advertising access address, hardware whitening / CRC-24, interrupt driven receive loop (RADIO interrupt), advertising channel hopping (TIMER3 compare interrupt), 1 MHz time stamps captured by PPI at the access address, 16 slot packet queue for the main loop |
| `ble_csa.h`, `ble_csa.c` | pure C (no hardware): channel selection algorithms #1 and #2, channel map helpers, channel index to RADIO frequency |
| `ble_pdu.h`, `ble_pdu.c` | pure C: CONNECT_IND, LL_CONNECTION_UPDATE_IND and LL_CHANNEL_MAP_IND parsing |
| `ble_follow.h`, `ble_follow.c` | pure C: the connection following state machine (device filter, connection setup from the CONNECT_IND, per-event channel and listening window with window widening, instants of updates, More Data / direction / gap tracking, LL_TERMINATE_IND, encryption start, supervision timeout). Python twin: [../../tests/ble_follow_model.py](../../tests/ble_follow_model.py); both are compared by the unit tests (the C files are compiled on the host with `tests/c/follow_driver.c`) |

`ble_radio.c` is the only file that touches the RADIO for BLE; it feeds the pure C logic with received packets and time stamps and
executes its decisions (timer started receive windows through PPI, in-event re-arm after 150 µs, hop alignment with the advertiser).
