# Roborock Local Plugin for Domoticz

Version: **1.0.1**

Local LAN plugin for older Roborock vacuum cleaners that use the legacy Xiaomi
miIO protocol.

No cloud service is required during normal operation.

## Compatibility

### Tested

- Roborock S5
- Model ID: `roborock.vacuum.s5`
- Firmware tested: `3.5.8_002034`

### Experimental

Other older Roborock devices that:

- can be configured in Xiaomi Home / Mi Home;
- respond through the local Xiaomi miIO protocol;
- use a local IP address and a 32-character token;
- are handled by `python-miio` as `roborock.vacuum.*`.

Newer models that require the Roborock application and the modern Roborock
protocol are not supported by this version.

## Features

- Start or resume cleaning
- Pause
- Stop
- Return to dock
- Spot cleaning
- Find robot
- Current status
- Battery level
- Fan mode
- Current cleaned area
- Current cleaning time
- Error status
- Carpet Boost switch
- Wi-Fi RSSI
- Main brush remaining
- Side brush remaining
- Filter remaining
- Sensor cleaning remaining
- Reset individual consumables
- Total cleaning count
- Total cleaned area
- Total cleaning duration
- Last cleaning details
- Do Not Disturb status
- DND schedule display
- Voice volume
- Voice test button
- Model and firmware information
- Automatic offline detection and recovery

Room cleaning is not enabled in version 1.0 because the tested S5 currently
returns an empty room mapping. Manual coordinate-based zones can be added later.

## Isolated Python environment

All libraries are installed in:

```text
/home/pi/domoticz/plugins/Roborock/.venv
```

Nothing is installed globally and other Domoticz plugins are not modified.

## Installation

Copy/extract the files into:

```text
/home/pi/domoticz/plugins/Roborock
```

Then run:

```bash
cd /home/pi/domoticz/plugins/Roborock
chmod +x install.sh update.sh uninstall.sh run_diagnostic.sh diagnostic.py
./install.sh
sudo systemctl restart domoticz
```

## Domoticz configuration

Open:

```text
Setup → Hardware → Add
```

Select:

```text
Roborock Local
```

Configure:

- **Vacuum IP address:** fixed local IP of the vacuum
- **Token:** 32-character Xiaomi miIO token
- **Model:** `auto` is recommended
- **Poll interval:** `30` seconds
- **Network timeout:** `5` seconds
- **Debug:** disabled during normal use

## Diagnostic

The diagnostic performs only read operations:

```bash
cd /home/pi/domoticz/plugins/Roborock
./run_diagnostic.sh 192.168.0.142 YOUR_TOKEN auto
```

The updated diagnostic completely redacts the token from both terminal output
and `diagnostic_result.json`.

## Updating

When installed from Git:

```bash
cd /home/pi/domoticz/plugins/Roborock
./update.sh
sudo systemctl restart domoticz
```

## Uninstalling

First remove the hardware from Domoticz, then:

```bash
cd /home/pi/domoticz/plugins/Roborock
./uninstall.sh
cd ..
rm -rf Roborock
sudo systemctl restart domoticz
```

## Changes in 1.0.1

- Fixed compatibility with `python-miio==0.5.12`, which does not provide
  `UnsupportedFeatureException` in `miio.exceptions`.
- Added compatibility with both `status()` and `vacuum_status()` method names.

## Notes

- Reserve the vacuum IP address in DHCP.
- The Domoticz server must be able to reach the vacuum over the local network.
- Commands and capabilities can differ between models and firmware versions.
- Unsupported optional functions are ignored instead of stopping the plugin.
- The token is stored in the Domoticz Hardware configuration. Treat it as a
  password and do not publish it.

## Credits

- `python-miio` by its contributors
- Domoticz Python Plugin System
- The original `domoticz-mirobot-plugin` project for early community work on
  Xiaomi robot vacuum integration

## Version 1.0.2

- Fixed compatibility with python-miio builds whose `RoborockVacuum` constructor does not accept `timeout`.
- Prevented false `Offline` status caused by a constructor error.
- Added controlled reconnection every 60 seconds without repeated `client is not connected` errors.


## Stability notes (v1.0.3)

- Only one basic `status` request is sent at each regular poll.
- Consumables, DND, Carpet Boost, history, voice volume and Wi-Fi are read one
  at a time on a rotating schedule.
- A failed optional query no longer marks the vacuum offline.
- The local protocol session is recreated automatically after a transient UDP
  timeout.
- The Error device is reserved for actual vacuum error codes.
- Do not keep the old Xiaomi Mi Robot Vacuum hardware enabled at the same time.
  Two plugins polling the same IP and token can cause unnecessary timeouts.


## Version 1.0.4

- Replaces python-miio's legacy AES-CBC payload implementation with the
  namespaced PyCryptodomeX backend.
- Prevents intermittent `UnsupportedAlgorithm: cipher AES in CBC mode is not
  supported` errors caused by cryptography/OpenSSL backend conflicts.
- Performs an offline AES-CBC self-test during `install.sh`.
- A command pressed while disconnected now triggers an immediate reconnect
  attempt instead of waiting for the scheduled reconnect cycle.
- No hardware configuration or Domoticz devices are deleted during update.
