# Bluetooth Protocols – BrickController2 Devices

Descriptions of the radio / Bluetooth protocols of devices supported by [BrickController2](https://github.com/J0EK3R/brickcontroller2), with a focus on **Mould King** modules.

All documents are written in Markdown and in English. Protocol details are derived from the BrickController2 source code and unit tests, datasheets and own analysis; derived (not documented) interpretations are marked as such in the documents.

## Contents

### Mould King

All Mould King modules below are controlled via **BLE advertising**: the app encodes its telegrams so that an XN297L-compatible 2.4 GHz frame appears on air (see [XN297L](Chips/XN297L.md)).

| Document | Device | Channels | Connect / Command identifiers |
|---|---|---|---|
| [MouldKing/MK3.0.md](MouldKing/MK3.0.md) | MK3.0 module | 2 analog (byte) + 2 on/off functions | `AA…55` / `66…99` |
| [MouldKing/MK3.8.md](MouldKing/MK3.8.md) | MK3.8 module | 4 analog (nibble) + left/right | `B1…C1` / `81…C2` |
| [MouldKing/MK4.0.md](MouldKing/MK4.0.md) | MK4.0 receiver | 4 analog (nibble) × 3 devices, shared telegram | `AD…52` / `7D…82` |
| [MouldKing/MK5.0.md](MouldKing/MK5.0.md) | MK5.0 tank module | drive, turret, shot, turn + turret lock | `AD…52` / `7D…82` (same as MK4.0) |
| [MouldKing/MK6.0.md](MouldKing/MK6.0.md) | MK6.0 module | 6 analog (byte) × 3 devices, telegram per device | `6D…92` / `61…63` |

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
    ├── MK3.0.md
    ├── MK3.8.md
    ├── MK4.0.md
    ├── MK5.0.md
    ├── MK6.0.md
    └── img/            # device images (PNG) and SVG comparison tables (BLE packet vs. XN297L frame)
```

## Conventions

- One Markdown file per device or chip, named after the device (`MK4.0.md`, `XN297L.md`).
- Byte sequences are written as hex bytes in transmission order (`71 0F 55`), multi-byte values as `0x…`.
- Every document starts with its sources and a "Last updated" date and ends with a list of open questions.
- Images live in an `img/` folder next to the document that uses them.

## Image credits

The device images in `MouldKing/img/mk*_image.png` are taken from [BrickController2](https://github.com/J0EK3R/brickcontroller2) (`BrickController2/UI/Images`), © István Murvai, Vít Německý and Contributors, MIT License.
