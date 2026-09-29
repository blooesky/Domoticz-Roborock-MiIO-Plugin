# Domoticz Roborock MiIO Plugin

A local LAN plugin for **Domoticz** that controls older **Roborock robot vacuum cleaners** using the legacy Xiaomi **miIO** protocol.

The plugin communicates directly with the vacuum using its **local IP address + 32-character miIO token**.

> **No cloud connection is required during normal operation.**

---

## Features

- Local LAN communication
- No cloud dependency during normal operation
- Dedicated isolated Python virtual environment (`.venv`)
- Automatic Roborock model detection
- Automatic reconnect
- Offline detection
- Start / Resume cleaning
- Pause cleaning
- Stop cleaning
- Return to Dock
- Spot Cleaning
- Find Robot
- Current vacuum status
- Battery level
- Fan mode selector
- Current cleaned area
- Current cleaning time
- Error status
- Carpet Boost control
- Wi-Fi signal strength
- Main Brush remaining life
- Side Brush remaining life
- Filter remaining life
- Sensor cleaning remaining time
- Reset consumables
- Total cleaning count
- Total cleaned area
- Total cleaning time
- Last cleaning information
- Do Not Disturb status
- DND schedule display
- Voice volume control
- Voice test
- Model and firmware information
- Read-only diagnostic tool

---

## Compatibility

### Tested

- **Roborock S5**
- Model ID: `roborock.vacuum.s5`
- Tested firmware: `3.5.8_002034`

### Experimental compatibility

Other older Roborock vacuum cleaners may also work if they:

- can be configured in **Xiaomi Home / Mi Home**
- use the legacy Xiaomi **miIO** local protocol
- have a local IP address
- have a valid 32-character miIO token
- are supported by `python-miio` as a `roborock.vacuum.*` device

Compatibility may differ depending on model and firmware.

### Not supported

New-generation Roborock devices that require the **Roborock app** and the modern Roborock protocol are not supported by this plugin version.

---

## Requirements

- Domoticz with Python plugin support
- Python 3
- Python virtual environment support (`python3-venv`)
- Roborock connected to the same local network as Domoticz
- Fixed or DHCP-reserved IP address for the vacuum
- Valid Xiaomi miIO token
- Linux / Raspberry Pi recommended

---

# Installation from GitHub

Go to the Domoticz plugins directory:

```bash
cd /home/pi/domoticz/plugins
```

Clone the repository:

```bash
git clone https://github.com/blooesky/Domoticz-Roborock-MiIO-Plugin.git Roborock-MiIO
```

Enter the plugin directory:

```bash
cd Roborock
```

Make the scripts executable:

```bash
chmod +x install.sh update.sh uninstall.sh run_diagnostic.sh diagnostic.py miio_crypto_compat.py
```

Run the installer:

```bash
./install.sh
```

Restart Domoticz:

```bash
sudo systemctl restart domoticz
```

The plugin should now appear in:

```text
Setup → Hardware
```

as:

```text
Roborock Local
```

---

# Manual installation

If you do not want to use Git, download the repository ZIP from GitHub.

Extract it so the plugin files are located directly in:

```text
/home/pi/domoticz/plugins/Roborock
```

The final folder should look similar to:

```text
Roborock/
├── plugin.py
├── roborock_client.py
├── miio_crypto_compat.py
├── diagnostic.py
├── run_diagnostic.sh
├── install.sh
├── update.sh
├── uninstall.sh
├── requirements.txt
└── README.md
```

Then run:

```bash
cd /home/pi/domoticz/plugins/Roborock
chmod +x install.sh update.sh uninstall.sh run_diagnostic.sh diagnostic.py miio_crypto_compat.py
./install.sh
sudo systemctl restart domoticz
```

---

# Python virtual environment

The installer automatically creates a dedicated Python virtual environment:

```text
/home/pi/domoticz/plugins/Roborock/.venv
```

All required Python packages are installed inside this directory.

The plugin does **not** install Python libraries globally and does not modify the Python environments used by other Domoticz plugins.

The environment includes the required packages such as:

```text
python-miio
click
pycryptodomex
```

plus their dependencies.

If `python3-venv` is not installed, install it first:

```bash
sudo apt update
sudo apt install python3-venv
```

Then run:

```bash
cd /home/pi/domoticz/plugins/Roborock
./install.sh
```

again.

---

# Domoticz configuration

After restarting Domoticz, open:

```text
Setup → Hardware
```

Add:

```text
Roborock Local
```

Configure the following fields.

## Vacuum IP address

Example:

```text
192.168.0.142
```

A DHCP reservation is strongly recommended so the vacuum always keeps the same IP address.

## miIO Token

Enter the 32-character hexadecimal Xiaomi miIO token.

Example format:

```text
0123456789abcdef0123456789abcdef
```

Treat the token like a password.

Do not publish it on GitHub or include it in screenshots or issue reports.

## Model

Recommended:

```text
auto
```

The plugin will try to detect the Roborock model automatically.

A model can also be entered manually, for example:

```text
roborock.vacuum.s5
```

## Poll interval

Recommended:

```text
30
```

The value is in seconds.

## Network timeout

Recommended:

```text
5
```

## Debug

Keep Debug disabled during normal operation.

Enable it only when troubleshooting.

---

# Devices created in Domoticz

The plugin can create the following devices:

```text
Control
Status
Battery
Fan Mode
Cleaned Area
Cleaning Time
Error
Carpet Boost
Wi-Fi Signal
Main Brush Remaining
Side Brush Remaining
Filter Remaining
Sensor Cleaning Remaining
Reset Consumable
Total Cleanings
Total Cleaned Area
Total Cleaning Time
Last Cleaning
Do Not Disturb
DND Schedule
Voice Volume
Test Voice
Device Info
```

Available devices and commands can differ between models and firmware versions.

---

# Main control

The main `Control` selector provides:

```text
Off
Start
Pause
Stop
Dock
Spot
Find
```

After a momentary command is executed, the selector returns to `Off`.

---

# Fan modes

Fan modes are read from the vacuum.

On the tested Roborock S5 the available modes are:

```text
Silent
Standard
Medium
Turbo
Gentle
Auto
```

Other compatible Roborock models may expose different fan modes.

---

# Consumables

The plugin displays the estimated remaining life of:

- Main Brush
- Side Brush
- Filter
- Sensors

The `Reset Consumable` selector can reset an item after replacement or maintenance:

```text
Main Brush
Side Brush
Filter
Sensors
```

---

# Do Not Disturb

The plugin reads the DND configuration directly from the vacuum.

It can display:

- DND enabled / disabled
- DND start time
- DND end time

The DND switch can enable or disable the current schedule.

---

# Voice volume

The vacuum voice volume can be controlled from Domoticz.

A separate `Test Voice` device can be used to test the current volume.

---

# Local miIO communication

Normal communication uses:

```text
Domoticz
   │
   │ Local LAN
   ▼
Roborock IP + miIO Token
```

The commands are sent directly to the vacuum.

Xiaomi Cloud is not required for normal plugin operation.

---

# AES-CBC compatibility layer

Legacy Xiaomi miIO communication uses AES-CBC encryption.

Some long-running Domoticz installations can experience cryptography/OpenSSL backend conflicts such as:

```text
UnsupportedAlgorithm: cipher AES in CBC mode is not supported
```

This plugin includes its own compatibility layer:

```text
miio_crypto_compat.py
```

and uses **PyCryptodomeX** for the legacy AES-CBC miIO payload encryption.

The installer performs an AES-CBC self-test automatically.

A successful installation should display:

```text
miIO AES-CBC backend OK: PyCryptodomeX AES-128-CBC
```

---

# Diagnostic tool

A read-only diagnostic utility is included.

It can be used to check the capabilities returned by a specific Roborock model.

Run:

```bash
cd /home/pi/domoticz/plugins/Roborock
./run_diagnostic.sh ROBOT_IP ROBOT_TOKEN auto
```

Example:

```bash
./run_diagnostic.sh 192.168.0.142 0123456789abcdef0123456789abcdef auto
```

The diagnostic performs read-only queries.

It does **not** start, stop or move the robot.

It checks data such as:

- Device model
- Firmware
- Vacuum status
- Battery
- Fan modes
- Consumables
- Cleaning history
- Last cleaning
- DND
- Carpet Mode
- Room mapping

The result is saved as:

```text
diagnostic_result.json
```

The diagnostic automatically redacts the miIO token from its output.

---

# Update from GitHub

If the plugin was installed using Git:

```bash
cd /home/pi/domoticz/plugins/Roborock
./update.sh
sudo systemctl restart domoticz
```

The update script:

1. runs `git pull`
2. checks/updates the `.venv`
3. installs any new Python dependencies
4. verifies the plugin files

The existing Domoticz hardware configuration and devices are not deleted.

---

# Manual update

If the plugin was installed manually, download the latest files and overwrite the existing files inside:

```text
/home/pi/domoticz/plugins/Roborock
```

Then run:

```bash
cd /home/pi/domoticz/plugins/Roborock
./install.sh
sudo systemctl restart domoticz
```

There is normally no need to remove and recreate the Roborock hardware in Domoticz.

---

# Uninstall

First remove the `Roborock Local` hardware from Domoticz.

Then run:

```bash
cd /home/pi/domoticz/plugins/Roborock
./uninstall.sh
```

The script removes the plugin virtual environment.

To completely remove the plugin:

```bash
cd /home/pi/domoticz/plugins
rm -rf Roborock
sudo systemctl restart domoticz
```

---

# Troubleshooting

## Plugin does not appear in Domoticz

Make sure `plugin.py` is directly inside:

```text
/home/pi/domoticz/plugins/Roborock
```

Then restart Domoticz:

```bash
sudo systemctl restart domoticz
```

## `python-miio could not be loaded`

Run:

```bash
cd /home/pi/domoticz/plugins/Roborock
./install.sh
sudo systemctl restart domoticz
```

## Vacuum appears offline

Check:

- vacuum IP address
- miIO token
- Wi-Fi connection
- DHCP reservation
- local network access
- firewall settings

Then run the diagnostic tool.

## Commands are delayed

Make sure another Xiaomi / Roborock plugin or service is not controlling the same vacuum at the same time.

It is recommended to use only one active integration for local miIO communication with the same robot.

## AES-CBC error

If you see:

```text
UnsupportedAlgorithm: cipher AES in CBC mode is not supported
```

run:

```bash
cd /home/pi/domoticz/plugins/Roborock
./install.sh
sudo systemctl restart domoticz
```

The current plugin uses its own PyCryptodomeX AES-CBC compatibility backend.

---

# Room cleaning and maps

Some legacy Roborock models expose additional miIO functionality such as:

- room / segment cleaning
- zone cleaning
- go-to coordinates
- map functions

These features are not enabled by default in the current plugin version because availability varies between models and firmware versions.

They may be added in future releases.

---

# What this plugin is based on

This project uses and builds on several open-source projects and documented interfaces.

## python-miio

Repository:

https://github.com/rytilahti/python-miio

`python-miio` provides the Xiaomi miIO protocol implementation and the `RoborockVacuum` integration used to communicate with compatible legacy Roborock devices.

The library supports local communication using the device IP address and token.

## PyCryptodome / PyCryptodomeX

Repository:

https://github.com/Legrandin/pycryptodome

The plugin uses the `pycryptodomex` package and its separate `Cryptodome` namespace for the AES-CBC compatibility layer used by legacy miIO communication.

## Domoticz Python Plugin System

Documentation:

https://wiki.domoticz.com/Developing_a_Python_plugin

The plugin itself is built using the Domoticz Python Plugin Framework.

## Original Domoticz Xiaomi Mi Robot plugin

Repository:

https://github.com/mrin/domoticz-mirobot-plugin

The older `domoticz-mirobot-plugin` project demonstrated Xiaomi Mi Robot / Roborock integration with Domoticz and also used `python-miio`.

This project was useful as an early reference for Domoticz vacuum integration.

**Domoticz Roborock MiIO Plugin is a new implementation.**

It does not require the old external `miio_server` architecture and instead uses:

- a dedicated per-plugin `.venv`
- direct local communication
- modern Domoticz devices
- additional Roborock information
- automatic reconnect logic
- diagnostic tools
- dedicated AES-CBC compatibility handling

---

# Repository

GitHub:

```text
https://github.com/blooesky/Domoticz-Roborock-MiIO-Plugin
```

Clone:

```bash
git clone https://github.com/blooesky/Domoticz-Roborock-MiIO-Plugin.git Roborock
```

---

# Security

The miIO token provides local control access to the vacuum.

Treat it like a password.

Never:

- publish the token on GitHub
- commit the token to the repository
- include it in screenshots
- include it in GitHub Issues
- include unredacted diagnostic files

The included diagnostic utility is designed to redact the token automatically.

---

# Disclaimer

This is an independent community project.

It is not affiliated with, endorsed by, or officially supported by Roborock, Xiaomi, Domoticz, or the maintainers of the third-party libraries referenced above.

Compatibility depends on the specific vacuum model, firmware version and local network configuration.

---

# Credits

Thanks to the developers and contributors of:

- [python-miio](https://github.com/rytilahti/python-miio)
- [PyCryptodome](https://github.com/Legrandin/pycryptodome)
- [Domoticz](https://github.com/domoticz/domoticz)
- [domoticz-mirobot-plugin](https://github.com/mrin/domoticz-mirobot-plugin)

