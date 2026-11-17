# XN297L sniffer – Firmware

Zephyr application for the **nRF52840 MDK USB Dongle** (makerdiary). It uses no Bluetooth stack:
the `RADIO` peripheral is programmed directly. Two receiver backends share one image, selected with
the serial command `mode`:

- `xn297l` (default after boot): raw GFSK receiver that synchronises on an XN297L sync word and
  reports the captured bytes as `P` lines.
- `ble`: Bluetooth LE sniffer (advertising channels 37/38/39, LE 1M, hardware whitening and CRC-24,
  every packet incl. bad CRC reported as `B` line; connection following etc. follows in later releases).

Both report as text lines over USB CDC.
Usage, command set, flashing and building: [../README.md](../README.md).

## Contents

| Path | Content |
|---|---|
| `CMakeLists.txt` | Zephyr build file (`west build -b nrf52840_mdk_usb_dongle firmware`) |
| `prj.conf` | Kconfig: USB CDC ACM, no Bluetooth stack, no logging/console on the data port, UF2 output |
| [boards/](boards/README.md) | devicetree overlay for the dongle (CDC ACM UART) |
| [src/](src/README.md) | C sources: command parser and main loop, buffered USB output, XN297L RADIO driver, BLE RADIO driver |
| [prebuilt/](prebuilt/README.md) | ready-to-flash `.uf2` built from this source |

## Build

```bash
# inside a west workspace (nRF Connect SDK or plain Zephyr), tested with Zephyr v3.7.0 / SDK 0.16.8
west build -b nrf52840_mdk_usb_dongle -p always path/to/Tools/xn297l-sniffer/firmware
# result: build/zephyr/zephyr.uf2
```

### Toolchain without root rights (Linux, x86_64)

Everything below goes into one folder (`$ZEP`), nothing is installed system-wide. This is the
setup the firmware was last built with (Python 3.12, `cmake` and `dtc` not needed on the system):

```bash
ZEP=$HOME/zephyr-build && mkdir -p $ZEP && cd $ZEP
python3 -m venv venv && . venv/bin/activate
pip install west ninja pyelftools pyyaml packaging pykwalify colorama canopen intelhex 'cmake<4'

# Zephyr v3.7.0 with the three modules this firmware needs (nRF HAL, CMSIS, libc)
mkdir ws && cd ws && west init --mr v3.7.0
west update --narrow -o=--depth=1 hal_nordic cmsis picolibc
pip install -r zephyr/scripts/requirements-base.txt

# Zephyr SDK 0.16.8: minimal package + ARM toolchain + host tools (provides dtc)
B=https://github.com/zephyrproject-rtos/sdk-ng/releases/download/v0.16.8
curl -LO $B/zephyr-sdk-0.16.8_linux-x86_64_minimal.tar.xz
curl -LO $B/toolchain_linux-x86_64_arm-zephyr-eabi.tar.xz
tar xf zephyr-sdk-0.16.8_linux-x86_64_minimal.tar.xz
tar xf toolchain_linux-x86_64_arm-zephyr-eabi.tar.xz -C zephyr-sdk-0.16.8
sh zephyr-sdk-0.16.8/zephyr-sdk-x86_64-hosttools-standalone-0.9.sh -y -d $PWD/zephyr-sdk-0.16.8/hosttools

# every new shell
export ZEPHYR_BASE=$ZEP/ws/zephyr ZEPHYR_TOOLCHAIN_VARIANT=zephyr
export ZEPHYR_SDK_INSTALL_DIR=$ZEP/zephyr-sdk-0.16.8
export PATH=$ZEP/zephyr-sdk-0.16.8/hosttools/sysroots/x86_64-pokysdk-linux/usr/bin:$PATH
. $ZEP/venv/bin/activate
west build -b nrf52840_mdk_usb_dongle -p always -d /tmp/xn297l-build path/to/Tools/xn297l-sniffer/firmware
```

`cmake` 4.x is too new for Zephyr 3.7 (hence `cmake<4`). The unchanged 1.1.0 sources built with this
setup are byte-identical to `prebuilt/xn297l_sniffer_nrf52840_mdk_usb_dongle.uf2`, i.e. the build is reproducible.
