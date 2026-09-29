# Roborock Local plugin for Domoticz
#
# Tested model:
#   Roborock S5 (roborock.vacuum.s5)
#
# Experimental compatibility:
#   Older Roborock models using Xiaomi Home/Mi Home and the legacy local
#   Xiaomi miIO protocol (local IP + 32-character token).
#
"""
<plugin key="RoborockLocal" name="Roborock Local" author="Everpro" version="1.0.4">
    <description>
        <h2>Roborock Local</h2>
        <p>Local LAN control for older Roborock vacuum cleaners using Xiaomi miIO.</p>
        <p>Tested with Roborock S5. Other legacy roborock.vacuum.* models are experimental.</p>
    </description>
    <params>
        <param field="Address" label="Vacuum IP address" width="200px" required="true" default=""/>
        <param field="Password" label="32-character miIO token" width="300px" required="true" password="true" default=""/>
        <param field="Mode1" label="Model (auto or model ID)" width="250px" required="true" default="auto"/>
        <param field="Mode2" label="Poll interval (seconds)" width="100px" required="true" default="30"/>
        <param field="Mode3" label="Network timeout (seconds)" width="100px" required="true" default="5"/>
        <param field="Mode6" label="Debug" width="100px">
            <options>
                <option label="Disabled" value="0" default="true"/>
                <option label="Enabled" value="1"/>
            </options>
        </param>
    </params>
</plugin>
"""

from __future__ import annotations

import glob
import ipaddress
import os
import re
import sys
import time
from datetime import datetime
from typing import Any, Optional

import Domoticz


PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))


def _activate_plugin_venv() -> None:
    candidates = [
        os.path.join(PLUGIN_DIR, ".venv", "lib", "python*", "site-packages"),
        os.path.join(PLUGIN_DIR, ".venv", "Lib", "site-packages"),
    ]
    for pattern in candidates:
        for path in glob.glob(pattern):
            if os.path.isdir(path) and path not in sys.path:
                sys.path.insert(0, path)


_activate_plugin_venv()

IMPORT_ERROR: Optional[Exception] = None
try:
    from roborock_client import RoborockLocalClient
except Exception as exc:  # The plugin must still load and show a useful error.
    RoborockLocalClient = None  # type: ignore[assignment]
    IMPORT_ERROR = exc


UNIT_CONTROL = 1
UNIT_STATUS = 2
UNIT_BATTERY = 3
UNIT_FAN_MODE = 4
UNIT_CLEAN_AREA = 5
UNIT_CLEAN_TIME = 6
UNIT_ERROR = 7
UNIT_CARPET_BOOST = 8
UNIT_WIFI_SIGNAL = 9
UNIT_MAIN_BRUSH = 10
UNIT_SIDE_BRUSH = 11
UNIT_FILTER = 12
UNIT_SENSORS = 13
UNIT_RESET_CONSUMABLE = 14
UNIT_TOTAL_CLEANINGS = 15
UNIT_TOTAL_AREA = 16
UNIT_TOTAL_TIME = 17
UNIT_LAST_CLEANING = 18
UNIT_DND = 19
UNIT_DND_SCHEDULE = 20
UNIT_VOICE_VOLUME = 21
UNIT_TEST_VOICE = 22
UNIT_DEVICE_INFO = 23


CONTROL_LEVELS = {
    10: "start",
    20: "pause",
    30: "stop",
    40: "dock",
    50: "spot",
    60: "find",
}

RESET_LEVELS = {
    10: "main_brush",
    20: "side_brush",
    30: "filter",
    40: "sensors",
}


class BasePlugin:
    def __init__(self) -> None:
        self.client: Optional[Any] = None
        self.poll_interval = 30
        self.timeout = 5
        self.next_poll = 0.0
        self.next_auxiliary_poll = 0.0
        self.next_reconnect = 0.0
        self.reconnect_interval = 60
        self.auxiliary_interval = 120
        self.auxiliary_sections = [
            "consumables",
            "dnd",
            "carpet",
            "voice_volume",
            "history",
            "last_clean",
            "device_info",
        ]
        self.auxiliary_index = 0
        self.failure_count = 0
        self.offline_threshold = 5
        self.connected = False
        self.busy = False
        self.debug_enabled = False
        self.last_status: dict[str, Any] = {}
        self.last_extended: dict[str, Any] = {}
        self.last_dnd_window = (22, 0, 8, 0)
        self.fan_level_to_name: dict[int, str] = {}
        self.fan_name_to_level: dict[str, int] = {}

    def onStart(self) -> None:
        self.debug_enabled = Parameters.get("Mode6", "0") == "1"
        if self.debug_enabled:
            Domoticz.Debugging(1)

        self._create_devices()
        self._update_text(UNIT_STATUS, "Starting")

        try:
            ipaddress.ip_address(Parameters.get("Address", "").strip())
        except ValueError:
            self._fatal("Invalid vacuum IP address")
            return

        token = Parameters.get("Password", "").strip()
        if not re.fullmatch(r"[0-9a-fA-F]{32}", token):
            self._fatal("Invalid token: expected 32 hexadecimal characters")
            return

        try:
            self.poll_interval = max(10, int(Parameters.get("Mode2", "30")))
        except (TypeError, ValueError):
            self.poll_interval = 30

        try:
            self.timeout = max(1, min(30, int(Parameters.get("Mode3", "5"))))
        except (TypeError, ValueError):
            self.timeout = 5

        Domoticz.Heartbeat(10)

        if IMPORT_ERROR is not None or RoborockLocalClient is None:
            self._fatal(
                "python-miio could not be loaded. Run ./install.sh. Error: {}".format(
                    IMPORT_ERROR
                )
            )
            return

        self.client = RoborockLocalClient(
            ip_address=Parameters["Address"],
            token=token,
            model=Parameters.get("Mode1", "auto"),
            timeout=self.timeout,
            debug_callback=self._debug,
        )
        if self._attempt_connect(initial=True):
            self._poll()

    def onStop(self) -> None:
        Domoticz.Log("Roborock Local plugin stopped")

    def onCommand(self, Unit: int, Command: str, Level: int, Hue: int) -> None:
        if self.client is None:
            Domoticz.Error("Roborock command cannot run because the client is not initialized")
            self._reset_momentary_command(Unit)
            return

        # A command should not wait for the scheduled reconnect interval. Try to
        # restore the local session immediately, then execute the command.
        if not self.connected:
            Domoticz.Log("Roborock is reconnecting before executing the command")
            self.next_reconnect = 0.0
            if not self._attempt_connect(initial=False):
                Domoticz.Error("Roborock command was not sent because reconnection failed")
                self._reset_momentary_command(Unit)
                return

        if self.busy:
            Domoticz.Error("Roborock command ignored because another operation is active")
            self._reset_momentary_command(Unit)
            return

        self.busy = True
        try:
            self._debug(
                "Command received: Unit={} Command={} Level={}".format(
                    Unit, Command, Level
                )
            )

            if Unit == UNIT_CONTROL:
                action = CONTROL_LEVELS.get(int(Level))
                if action:
                    self.client.command(action)
                    Domoticz.Log("Roborock command executed: {}".format(action))
                self._update_selector(UNIT_CONTROL, 0)

            elif Unit == UNIT_FAN_MODE:
                preset_name = self.fan_level_to_name.get(int(Level))
                if preset_name:
                    self.client.set_fan_mode(preset_name)
                    Domoticz.Log("Roborock fan mode set to {}".format(preset_name))

            elif Unit == UNIT_CARPET_BOOST:
                enabled = self._command_is_on(Command, Level)
                self.client.set_carpet_boost(
                    enabled,
                    self.last_status.get("carpet_parameters"),
                )
                self._update_switch(UNIT_CARPET_BOOST, enabled)

            elif Unit == UNIT_RESET_CONSUMABLE:
                consumable = RESET_LEVELS.get(int(Level))
                if consumable:
                    self.client.reset_consumable(consumable)
                    Domoticz.Log("Roborock consumable reset: {}".format(consumable))
                self._update_selector(UNIT_RESET_CONSUMABLE, 0)
                self._schedule_auxiliary_first("consumables")

            elif Unit == UNIT_DND:
                enabled = self._command_is_on(Command, Level)
                self.client.set_dnd_enabled(enabled, *self.last_dnd_window)
                self._update_switch(UNIT_DND, enabled)

            elif Unit == UNIT_VOICE_VOLUME:
                volume = self._extract_level(Command, Level)
                self.client.set_voice_volume(volume)
                self._update_dimmer(UNIT_VOICE_VOLUME, volume)

            elif Unit == UNIT_TEST_VOICE:
                self.client.command("test_voice")
                self._update_switch(UNIT_TEST_VOICE, False)

            else:
                Domoticz.Error("Unsupported Roborock command unit: {}".format(Unit))
                return

            self.failure_count = 0
            self.connected = True
            self.next_poll = 0.0
        except Exception as exc:
            Domoticz.Error(
                "Roborock command failed: {}: {}".format(type(exc).__name__, exc)
            )
            try:
                self.client.refresh_protocol()
            except Exception:
                pass
            self.next_poll = 0.0
            if Unit in (UNIT_CONTROL, UNIT_RESET_CONSUMABLE, UNIT_TEST_VOICE):
                if Unit in Devices:
                    self._update_selector(Unit, 0) if Unit != UNIT_TEST_VOICE else self._update_switch(Unit, False)
        finally:
            self.busy = False

    def onHeartbeat(self) -> None:
        if self.busy or self.client is None:
            return

        now = time.monotonic()
        if not self.connected:
            if now >= self.next_reconnect and self._attempt_connect(initial=False):
                self._poll()
            return

        if now >= self.next_poll:
            self._poll()

    def _attempt_connect(self, initial: bool) -> bool:
        if self.client is None or self.busy:
            return False

        self.busy = True
        try:
            identity = self.client.connect()
            was_connected = self.connected
            self.connected = True
            self.failure_count = 0
            self.next_poll = 0.0
            self.next_auxiliary_poll = 0.0
            self.next_reconnect = 0.0

            self._update_text(
                UNIT_DEVICE_INFO,
                "{} | FW {} | {}".format(
                    identity.model,
                    identity.firmware or "unknown",
                    identity.ip_address,
                ),
            )
            self._build_fan_selector(self.client.fan_presets)
            self._clear_timed_out()

            if initial or not was_connected:
                Domoticz.Log(
                    "Roborock Local connected: {} firmware {} | crypto {}".format(
                        identity.model,
                        identity.firmware or "unknown",
                        getattr(self.client, "crypto_backend", "unknown"),
                    )
                )
            return True
        except Exception as exc:
            self.connected = False
            self.next_reconnect = time.monotonic() + self.reconnect_interval
            message = "{}: {}".format(type(exc).__name__, exc)
            Domoticz.Error("Roborock connection setup failed: {}".format(message))
            self._update_text(UNIT_STATUS, "Reconnecting")
            return False
        finally:
            self.busy = False

    def _poll(self) -> None:
        if self.client is None or not self.connected:
            return

        self.busy = True
        core_success = False
        try:
            status = self.client.read_status()
            core_success = True
            self.last_status = status
            self._apply_status(status)

            if self.failure_count:
                Domoticz.Log(
                    "Roborock Local communication restored after {} failed poll(s)".format(
                        self.failure_count
                    )
                )
            self.failure_count = 0
            self.connected = True
            self._clear_timed_out()

            now = time.monotonic()
            if now >= self.next_auxiliary_poll:
                self._poll_one_auxiliary()
                self.next_auxiliary_poll = now + self.auxiliary_interval
        except Exception as exc:
            self._communication_failure(exc, immediate=False)
        finally:
            # Retry a failed basic status sooner than the normal poll interval.
            delay = self.poll_interval if core_success else min(15, self.poll_interval)
            self.next_poll = time.monotonic() + delay
            self.busy = False

    def _poll_one_auxiliary(self) -> None:
        if self.client is None or not self.auxiliary_sections:
            return

        section = self.auxiliary_sections[
            self.auxiliary_index % len(self.auxiliary_sections)
        ]
        self.auxiliary_index = (self.auxiliary_index + 1) % len(
            self.auxiliary_sections
        )

        try:
            partial = self.client.read_auxiliary(section)
            self.last_extended.update(partial)
            self._apply_extended(partial)
            self._debug("Auxiliary section updated: {}".format(section))
        except Exception as exc:
            # An auxiliary value is not proof that the vacuum is offline. Keep
            # the basic status online and try this section again on the next
            # rotation.
            Domoticz.Log(
                "Roborock optional '{}' read skipped: {}: {}".format(
                    section, type(exc).__name__, exc
                )
            )
            try:
                self.client.refresh_protocol()
            except Exception:
                pass

    def _schedule_auxiliary_first(self, section: str) -> None:
        if section in self.auxiliary_sections:
            self.auxiliary_index = self.auxiliary_sections.index(section)
        self.next_auxiliary_poll = 0.0

    def _apply_status(self, status: dict[str, Any]) -> None:
        state = status.get("state") or "Unknown"
        battery = self._clamp(status.get("battery", 0), 0, 100)
        area = float(status.get("clean_area", 0.0) or 0.0)
        cleaning_minutes = float(status.get("clean_time_seconds", 0.0) or 0.0) / 60.0

        self._update_text(UNIT_STATUS, str(state), battery=battery)
        self._update_percentage(UNIT_BATTERY, battery)
        self._update_custom(UNIT_CLEAN_AREA, area, decimals=1, battery=battery)
        self._update_custom(UNIT_CLEAN_TIME, cleaning_minutes, decimals=0, battery=battery)

        error_code = int(status.get("error_code", 0) or 0)
        error_text = str(status.get("error") or "No error")
        if bool(status.get("got_error")) or error_code:
            self._update_alert(
                UNIT_ERROR,
                4,
                "{} ({})".format(error_text, error_code),
                battery=battery,
            )
        else:
            self._update_alert(UNIT_ERROR, 1, "No error", battery=battery)

        fan_value = status.get("fan_value")
        if fan_value is not None:
            preset_name = self._fan_name_from_value(int(fan_value))
            selector_level = self.fan_name_to_level.get(preset_name)
            if selector_level is not None:
                self._update_selector(UNIT_FAN_MODE, selector_level, battery=battery)

        carpet_enabled = status.get("carpet_enabled")
        if carpet_enabled is not None:
            self._update_switch(UNIT_CARPET_BOOST, bool(carpet_enabled), battery=battery)

        dnd_enabled = status.get("dnd_enabled")
        if dnd_enabled is not None:
            self._update_switch(UNIT_DND, bool(dnd_enabled), battery=battery)
            start_text = self._normalise_time_text(status.get("dnd_start"))
            end_text = self._normalise_time_text(status.get("dnd_end"))
            if start_text and end_text:
                self._update_text(
                    UNIT_DND_SCHEDULE,
                    "{} – {}".format(start_text, end_text),
                    battery=battery,
                )
                parsed_start = self._parse_time(start_text)
                parsed_end = self._parse_time(end_text)
                if parsed_start and parsed_end:
                    self.last_dnd_window = (
                        parsed_start[0],
                        parsed_start[1],
                        parsed_end[0],
                        parsed_end[1],
                    )

    def _apply_extended(self, extended: dict[str, Any]) -> None:
        battery = self._clamp(self.last_status.get("battery", 0), 0, 100)
        wifi_rssi = extended.get("wifi_rssi")
        if wifi_rssi is not None:
            self._update_custom(UNIT_WIFI_SIGNAL, float(wifi_rssi), decimals=0, battery=battery)

        consumables = extended.get("consumables") or {}
        unit_map = {
            "main_brush": UNIT_MAIN_BRUSH,
            "side_brush": UNIT_SIDE_BRUSH,
            "filter": UNIT_FILTER,
            "sensors": UNIT_SENSORS,
        }
        for key, unit in unit_map.items():
            remaining = (consumables.get(key) or {}).get("remaining_percent")
            if remaining is not None:
                self._update_percentage(unit, self._clamp(remaining, 0, 100), battery=battery)

        history = extended.get("history") or {}
        if history:
            self._update_custom(
                UNIT_TOTAL_CLEANINGS,
                float(history.get("count", 0) or 0),
                decimals=0,
                battery=battery,
            )
            self._update_custom(
                UNIT_TOTAL_AREA,
                float(history.get("total_area", 0.0) or 0.0),
                decimals=1,
                battery=battery,
            )
            total_hours = float(history.get("total_duration_seconds", 0.0) or 0.0) / 3600.0
            self._update_custom(
                UNIT_TOTAL_TIME,
                total_hours,
                decimals=1,
                battery=battery,
            )

        last_clean = extended.get("last_clean") or {}
        if last_clean:
            self._update_text(
                UNIT_LAST_CLEANING,
                self._format_last_clean(last_clean),
                battery=battery,
            )

        volume = extended.get("voice_volume")
        if volume is not None:
            self._update_dimmer(
                UNIT_VOICE_VOLUME,
                self._clamp(volume, 0, 100),
                battery=battery,
            )

        dnd = extended.get("dnd") or {}
        if dnd:
            self._update_switch(UNIT_DND, bool(dnd.get("enabled")), battery=battery)
            start_text = self._normalise_time_text(dnd.get("start"))
            end_text = self._normalise_time_text(dnd.get("end"))
            if start_text and end_text:
                self._update_text(
                    UNIT_DND_SCHEDULE,
                    "{} – {}".format(start_text, end_text),
                    battery=battery,
                )
                parsed_start = self._parse_time(start_text)
                parsed_end = self._parse_time(end_text)
                if parsed_start and parsed_end:
                    self.last_dnd_window = (
                        parsed_start[0], parsed_start[1],
                        parsed_end[0], parsed_end[1],
                    )

        carpet = extended.get("carpet") or {}
        if carpet:
            self._update_switch(
                UNIT_CARPET_BOOST, bool(carpet.get("enabled")), battery=battery
            )
            parameters = carpet.get("parameters")
            if isinstance(parameters, dict):
                self.last_status["carpet_parameters"] = parameters

        if "wifi_rssi" in extended or "wifi_ssid" in extended:
            identity_parts = []
            if self.client is not None and getattr(self.client, "identity", None) is not None:
                identity = self.client.identity
                identity_parts.append(identity.model)
                identity_parts.append("FW {}".format(identity.firmware or "unknown"))
            stored_rssi = self.last_extended.get("wifi_rssi")
            if stored_rssi is not None:
                identity_parts.append("Wi-Fi {} dBm".format(int(stored_rssi)))
            stored_ssid = self.last_extended.get("wifi_ssid")
            if stored_ssid:
                identity_parts.append(str(stored_ssid))
            if identity_parts:
                self._update_text(
                    UNIT_DEVICE_INFO, " | ".join(identity_parts), battery=battery
                )

    def _build_fan_selector(self, presets: dict[str, int]) -> None:
        if not presets:
            return

        preferred_order = ["Silent", "Standard", "Medium", "Turbo", "Gentle", "Auto", "Max", "Off"]
        ordered_names = [name for name in preferred_order if name in presets]
        ordered_names.extend(name for name in presets if name not in ordered_names)

        self.fan_level_to_name.clear()
        self.fan_name_to_level.clear()
        for index, name in enumerate(ordered_names, start=1):
            level = index * 10
            self.fan_level_to_name[level] = name
            self.fan_name_to_level[name] = level

        options = {
            "LevelActions": "|" * len(ordered_names),
            "LevelNames": "Off|" + "|".join(ordered_names),
            "LevelOffHidden": "true",
            "SelectorStyle": "0",
        }
        device = Devices.get(UNIT_FAN_MODE)
        if device is not None and getattr(device, "Options", None) != options:
            try:
                device.Options = options
                device.Update(
                    nValue=device.nValue,
                    sValue=device.sValue,
                    UpdateOptions=True,
                )
            except TypeError:
                # Older Domoticz builds do not support UpdateOptions.
                self._debug("Domoticz does not support dynamic selector options")
            except Exception as exc:
                self._debug("Unable to update fan selector options: {}".format(exc))

    def _fan_name_from_value(self, fan_value: int) -> str:
        if self.client is None:
            return ""
        for name, value in self.client.fan_presets.items():
            if int(value) == int(fan_value):
                return name
        return ""

    def _create_devices(self) -> None:
        selector_control = {
            "LevelActions": "||||||",
            "LevelNames": "Off|Start|Pause|Stop|Dock|Spot|Find",
            "LevelOffHidden": "false",
            "SelectorStyle": "0",
        }
        selector_fan = {
            "LevelActions": "||||||",
            "LevelNames": "Off|Silent|Standard|Medium|Turbo|Gentle|Auto",
            "LevelOffHidden": "true",
            "SelectorStyle": "0",
        }
        selector_reset = {
            "LevelActions": "||||",
            "LevelNames": "Off|Main Brush|Side Brush|Filter|Sensors",
            "LevelOffHidden": "false",
            "SelectorStyle": "0",
        }

        self._ensure_device(UNIT_CONTROL, "Control", TypeName="Selector Switch", Options=selector_control)
        self._ensure_device(UNIT_STATUS, "Status", TypeName="Text")
        self._ensure_device(UNIT_BATTERY, "Battery", TypeName="Percentage")
        self._ensure_device(UNIT_FAN_MODE, "Fan Mode", TypeName="Selector Switch", Options=selector_fan)
        self._ensure_device(UNIT_CLEAN_AREA, "Cleaned Area", TypeName="Custom", Options={"Custom": "1;m²"})
        self._ensure_device(UNIT_CLEAN_TIME, "Cleaning Time", TypeName="Custom", Options={"Custom": "1;min"})
        self._ensure_device(UNIT_ERROR, "Error", TypeName="Alert")
        self._ensure_device(UNIT_CARPET_BOOST, "Carpet Boost", TypeName="Switch")
        self._ensure_device(UNIT_WIFI_SIGNAL, "Wi-Fi Signal", TypeName="Custom", Options={"Custom": "1;dBm"})
        self._ensure_device(UNIT_MAIN_BRUSH, "Main Brush Remaining", TypeName="Percentage")
        self._ensure_device(UNIT_SIDE_BRUSH, "Side Brush Remaining", TypeName="Percentage")
        self._ensure_device(UNIT_FILTER, "Filter Remaining", TypeName="Percentage")
        self._ensure_device(UNIT_SENSORS, "Sensor Cleaning Remaining", TypeName="Percentage")
        self._ensure_device(UNIT_RESET_CONSUMABLE, "Reset Consumable", TypeName="Selector Switch", Options=selector_reset)
        self._ensure_device(UNIT_TOTAL_CLEANINGS, "Total Cleanings", TypeName="Custom", Options={"Custom": "1;cleanings"})
        self._ensure_device(UNIT_TOTAL_AREA, "Total Cleaned Area", TypeName="Custom", Options={"Custom": "1;m²"})
        self._ensure_device(UNIT_TOTAL_TIME, "Total Cleaning Time", TypeName="Custom", Options={"Custom": "1;h"})
        self._ensure_device(UNIT_LAST_CLEANING, "Last Cleaning", TypeName="Text")
        self._ensure_device(UNIT_DND, "Do Not Disturb", TypeName="Switch")
        self._ensure_device(UNIT_DND_SCHEDULE, "DND Schedule", TypeName="Text")
        self._ensure_device(UNIT_VOICE_VOLUME, "Voice Volume", TypeName="Switch", Switchtype=7)
        self._ensure_device(UNIT_TEST_VOICE, "Test Voice", TypeName="Switch", Switchtype=9)
        self._ensure_device(UNIT_DEVICE_INFO, "Device Info", TypeName="Text")

    def _ensure_device(self, unit: int, name: str, **kwargs: Any) -> None:
        if unit in Devices:
            return
        Domoticz.Device(Name=name, Unit=unit, Used=1, **kwargs).Create()

    def _fatal(self, message: str) -> None:
        self.connected = False
        Domoticz.Error(message)
        self._update_text(UNIT_STATUS, message)
        self._update_alert(UNIT_ERROR, 4, message)

    def _communication_failure(self, exc: Exception, immediate: bool) -> None:
        self.failure_count += 1
        message = "{}: {}".format(type(exc).__name__, exc)

        # A single UDP timeout is common on older miIO devices and does not mean
        # the vacuum is offline. Recreate the protocol session and retry.
        if self.failure_count == 1:
            Domoticz.Log("Roborock transient communication error: {}".format(message))
        else:
            self._debug(
                "Roborock communication retry {}/{}: {}".format(
                    self.failure_count, self.offline_threshold, message
                )
            )

        if self.client is not None:
            try:
                self.client.refresh_protocol()
            except Exception as refresh_exc:
                self._debug("Protocol refresh failed: {}".format(refresh_exc))

        if immediate or self.failure_count >= self.offline_threshold:
            self.connected = False
            self.next_reconnect = time.monotonic() + self.reconnect_interval
            self._update_text(UNIT_STATUS, "Offline")
            # UNIT_ERROR is reserved for actual vacuum error codes. A network
            # timeout must not alternate that sensor between Communication error
            # and No error.
            self._mark_timed_out()

    def _mark_timed_out(self) -> None:
        for device in Devices.values():
            try:
                device.Update(
                    nValue=device.nValue,
                    sValue=device.sValue,
                    TimedOut=1,
                    SuppressTriggers=True,
                )
            except TypeError:
                try:
                    device.Update(
                        nValue=device.nValue,
                        sValue=device.sValue,
                        TimedOut=1,
                    )
                except Exception:
                    pass
            except Exception:
                pass

    def _clear_timed_out(self) -> None:
        for device in Devices.values():
            if not getattr(device, "TimedOut", 0):
                continue
            try:
                device.Update(
                    nValue=device.nValue,
                    sValue=device.sValue,
                    TimedOut=0,
                    SuppressTriggers=True,
                )
            except TypeError:
                try:
                    device.Update(
                        nValue=device.nValue,
                        sValue=device.sValue,
                        TimedOut=0,
                    )
                except Exception:
                    pass
            except Exception:
                pass

    def _update(
        self,
        unit: int,
        n_value: int,
        s_value: str,
        battery: Optional[int] = None,
    ) -> None:
        device = Devices.get(unit)
        if device is None:
            return
        kwargs: dict[str, Any] = {
            "nValue": int(n_value),
            "sValue": str(s_value),
            "TimedOut": 0,
        }
        if battery is not None:
            kwargs["BatteryLevel"] = int(self._clamp(battery, 0, 100))

        desired_battery = kwargs.get("BatteryLevel", getattr(device, "BatteryLevel", 255))
        if (
            int(getattr(device, "nValue", 0)) == int(n_value)
            and str(getattr(device, "sValue", "")) == str(s_value)
            and int(getattr(device, "TimedOut", 0) or 0) == 0
            and int(getattr(device, "BatteryLevel", desired_battery)) == int(desired_battery)
        ):
            return

        try:
            device.Update(**kwargs)
        except TypeError:
            kwargs.pop("TimedOut", None)
            device.Update(**kwargs)

    def _update_text(self, unit: int, text: str, battery: Optional[int] = None) -> None:
        self._update(unit, 0, str(text), battery)

    def _update_alert(self, unit: int, level: int, text: str, battery: Optional[int] = None) -> None:
        self._update(unit, int(level), str(text), battery)

    def _update_percentage(self, unit: int, value: float, battery: Optional[int] = None) -> None:
        value = self._clamp(value, 0, 100)
        self._update(unit, 0, "{:.0f}".format(value), battery)

    def _update_custom(
        self,
        unit: int,
        value: float,
        decimals: int = 1,
        battery: Optional[int] = None,
    ) -> None:
        formatted = ("{:." + str(decimals) + "f}").format(float(value))
        self._update(unit, 0, formatted, battery)

    def _update_switch(self, unit: int, enabled: bool, battery: Optional[int] = None) -> None:
        self._update(unit, 1 if enabled else 0, "On" if enabled else "Off", battery)

    def _update_selector(self, unit: int, level: int, battery: Optional[int] = None) -> None:
        level = int(level)
        self._update(unit, 1 if level > 0 else 0, str(level), battery)

    def _update_dimmer(self, unit: int, level: float, battery: Optional[int] = None) -> None:
        level_int = int(self._clamp(level, 0, 100))
        self._update(unit, 1 if level_int > 0 else 0, str(level_int), battery)

    def _reset_momentary_command(self, unit: int) -> None:
        """Return momentary selectors/buttons to Off after a failed command."""
        if unit not in Devices:
            return
        if unit in (UNIT_CONTROL, UNIT_RESET_CONSUMABLE):
            self._update_selector(unit, 0)
        elif unit == UNIT_TEST_VOICE:
            self._update_switch(unit, False)

    @staticmethod
    def _command_is_on(command: str, level: int) -> bool:
        command_lower = str(command).strip().lower()
        if command_lower == "on":
            return True
        if command_lower == "off":
            return False
        return int(level or 0) > 0

    @staticmethod
    def _extract_level(command: str, level: int) -> int:
        command_lower = str(command).strip().lower()
        if command_lower == "off":
            return 0
        if command_lower == "on" and int(level or 0) == 0:
            return 50
        return int(level or 0)

    @staticmethod
    def _clamp(value: Any, minimum: float, maximum: float) -> float:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            numeric = minimum
        return max(minimum, min(maximum, numeric))

    @staticmethod
    def _normalise_time_text(value: Any) -> str:
        text = str(value or "")
        if not text:
            return ""
        # datetime.time is normally rendered as HH:MM:SS.
        return text[:5] if len(text) >= 5 else text

    @staticmethod
    def _parse_time(value: str) -> Optional[tuple[int, int]]:
        try:
            hour, minute = value.split(":", 1)
            return int(hour), int(minute)
        except Exception:
            return None

    @staticmethod
    def _format_last_clean(last_clean: dict[str, Any]) -> str:
        start = last_clean.get("start")
        if isinstance(start, datetime):
            start_text = start.strftime("%Y-%m-%d %H:%M")
        else:
            start_text = str(start or "Unknown")
        duration_min = int(round(float(last_clean.get("duration_seconds", 0) or 0) / 60.0))
        area = float(last_clean.get("area", 0.0) or 0.0)
        complete = "Completed" if last_clean.get("complete") else "Interrupted"
        error_code = int(last_clean.get("error_code", 0) or 0)
        if error_code:
            complete = "Error {}: {}".format(
                error_code,
                last_clean.get("error") or "Unknown",
            )
        return "{} | {:.1f} m² | {} min | {}".format(
            start_text,
            area,
            duration_min,
            complete,
        )

    def _debug(self, message: str) -> None:
        if self.debug_enabled:
            Domoticz.Debug(str(message))


_global_plugin = BasePlugin()


def onStart() -> None:
    _global_plugin.onStart()


def onStop() -> None:
    _global_plugin.onStop()


def onCommand(Unit: int, Command: str, Level: int, Hue: int) -> None:
    _global_plugin.onCommand(Unit, Command, Level, Hue)


def onHeartbeat() -> None:
    _global_plugin.onHeartbeat()
