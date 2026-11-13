# Mould King

Protocol descriptions of the Mould King receiver modules and of the original MK4.0 handset.
Overview of all vendors: [../README.md](../README.md).

All modules except the MKH4.0 are controlled via **BLE advertising**: the app sends telegrams that
appear on air as XN297L frames (see [../Chips/XN297L.md](../Chips/XN297L.md)). The MKH4.0 hub is a
real BLE peripheral and is controlled via a **GATT connection**.

## Contents

| File | Content |
|---|---|
| [MK3.0.md](MK3.0.md) | MK3.0 module – BLE advertising, 2 analog channels (byte) + 2 on/off functions |
| [MK3.8.md](MK3.8.md) | MK3.8 module – BLE advertising, 4 analog channels (nibble) + left/right |
| [MK4.0.md](MK4.0.md) | MK4.0 receiver – BLE advertising, 4 analog channels (nibble) × 3 devices in one shared telegram; photos of housing and receiver board |
| [MK4.0-Remote.md](MK4.0-Remote.md) | original MK4.0 2.4 GHz handset – native XN297L frames, measured with the [XN297L sniffer](../Tools/xn297l-sniffer/README.md): binding, channel hopping, telegram layout |
| [MK4.0-Remote-vs-BLE.md](MK4.0-Remote-vs-BLE.md) | layer-by-layer comparison of the original handset and the app (shared XN297L frame layer, different frequency, address and telegram format) |
| [MK4.0-Capture-Plan.md](MK4.0-Capture-Plan.md) | measurement plan for the open questions of the MK4.0 handset (hypotheses, no results yet) |
| [MK5.0.md](MK5.0.md) | MK5.0 tank module – BLE advertising, same telegrams as MK4.0: drive, turret, shot, turn + turret lock |
| [MK6.0.md](MK6.0.md) | MK6.0 module – BLE advertising, 6 analog channels (byte) × 3 devices, one telegram per device; housing photos |
| [MKH4.0.md](MKH4.0.md) | MKH4.0 hub – GATT service `0xAE3A`, ASCII command protocol, 4 ports (motor or servo); list of Mould King sets using the hub |
| [img/](img/README.md) | device images, photos and SVG frame diagrams used by these documents |
