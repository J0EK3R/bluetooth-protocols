# CaDA

Protocol descriptions of the CaDA devices.
Overview of all vendors: [../README.md](../README.md).

Unlike the other BLE advertising devices in this repository, the CaDA RaceCar is **paired** with
the app identifier during discovery.

The CJV1010 receiver and the CJV8011 handset form a separate 2.4 GHz system (no app, no BLE
documented); their radio protocol was captured with the XN297L sniffer in raw mode and the telegram decoded
(DSSS-like frames of 64-chip codewords, 4 bits per symbol, two direction masks); a smartphone
cannot emulate it via BLE, an own transmitter as a bridge is feasible. Investigation stopped on
2026-11-15.

## Contents

| File | Content |
|---|---|
| [RaceCar.md](RaceCar.md) | CaDA RaceCar (Rev1 and Rev2) – throttle, steering, front/rear lights. Rev1: CaDA encryption + XN297L frame (address "CAR") on BLE channel 38; Rev2: plain manufacturer data |
| [CJV1010.md](CJV1010.md) | CaDA CJV1010 – 4-channel 2.4 GHz receiver with built-in battery (Micro USB charging); product data, photos, battery; receiver-related protocol results |
| [CJV8011.md](CJV8011.md) | CaDA CJV8011 – original 4-channel 2.4 GHz handset for the CJV1010 (2 × AA, steering-wheel variant); product data, photos, **decoded radio protocol**, assessment smartphone / own transmitter |
| [CJV8011-Capture-Plan.md](CJV8011-Capture-Plan.md) | measurement plan and all runs (R0 … R4) for the CJV8011 / CJV1010 radio link; stopped on 2026-11-15 |
| [img/](img/README.md) | device images, product photos and SVG frame diagrams used by these documents |
