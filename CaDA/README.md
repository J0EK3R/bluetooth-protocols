# CaDA

Protocol descriptions of the CaDA devices.
Overview of all vendors: [../README.md](../README.md).

Unlike the other BLE advertising devices in this repository, the CaDA RaceCar is **paired** with
the app identifier during discovery.

The CJV1010 receiver and the CJV8011 handset form a separate 2.4 GHz system (no app, no BLE
documented); their radio protocol has not been captured yet – the documents so far contain the
product data, photos and the open questions.

## Contents

| File | Content |
|---|---|
| [RaceCar.md](RaceCar.md) | CaDA RaceCar (Rev1 and Rev2) – throttle, steering, front/rear lights. Rev1: CaDA encryption + XN297L frame (address "CAR") on BLE channel 38; Rev2: plain manufacturer data |
| [CJV1010.md](CJV1010.md) | CaDA CJV1010 – 4-channel 2.4 GHz receiver with built-in battery (Micro USB charging); product data, photos, open questions (protocol not yet captured) |
| [CJV8011.md](CJV8011.md) | CaDA CJV8011 – original 4-channel 2.4 GHz handset for the CJV1010 (2 × AA, steering-wheel variant); product data, photos, open questions (protocol not yet captured) |
| [img/](img/README.md) | device images, product photos and SVG frame diagrams used by these documents |
