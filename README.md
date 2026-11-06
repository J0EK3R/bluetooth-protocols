# Bluetooth Protocols – BrickController2 Devices

Descriptions of the radio / Bluetooth protocols of devices supported by [BrickController2](https://github.com/J0EK3R/brickcontroller2), with a focus on **Mould King** modules.

All documents are written in Markdown and in English. Protocol details are derived from the BrickController2 source code and unit tests, datasheets and own analysis; derived (not documented) interpretations are marked as such in the documents.

## Contents

### Mould King

| Document | Device | Transport |
|---|---|---|
| [MouldKing/MK4.0.md](MouldKing/MK4.0.md) | MK4.0 receiver (4 channels × 3 devices) | BLE advertising → XN297L frame |
| [MouldKing/MK6.0.md](MouldKing/MK6.0.md) | MK6.0 module (6 channels, per-device telegram) | BLE advertising → XN297L frame |

### Chips

| Document | Chip |
|---|---|
| [Chips/XN297L.md](Chips/XN297L.md) | Panchip XN297L 2.4 GHz GFSK transceiver (frame format, scrambler, CRC, BLE emulation) |

## Repository layout

```
.
├── README.md
├── Chips/
│   └── XN297L.md
└── MouldKing/
    ├── MK4.0.md
    ├── MK6.0.md
    └── img/            # SVG comparison tables (BLE packet vs. XN297L frame)
```

## Conventions

- One Markdown file per device or chip, named after the device (`MK4.0.md`, `XN297L.md`).
- Byte sequences are written as hex bytes in transmission order (`71 0F 55`), multi-byte values as `0x…`.
- Every document starts with its sources and a "Last updated" date and ends with a list of open questions.
- Images live in an `img/` folder next to the document that uses them.
