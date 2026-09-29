#!/usr/bin/env python3
"""Local Roborock client used by the Domoticz plugin.

The client targets older Roborock vacuum cleaners that use the legacy local
Xiaomi miIO protocol (IP address + 32-character token).
"""

from __future__ import annotations

from dataclasses import dataclass
import inspect
from datetime import timedelta
from typing import Any, Callable, Optional

from miio_crypto_compat import CRYPTO_BACKEND, install_miio_crypto_patch

# Install the stable legacy miIO AES-CBC backend before the first packet.
install_miio_crypto_patch()

from miio import RoborockVacuum


CONSUMABLE_PROTOCOL_NAMES = {
    "main_brush": "main_brush_work_time",
    "side_brush": "side_brush_work_time",
    "filter": "filter_work_time",
    "sensors": "sensor_dirty_time",
}

# Lifetimes used by Roborock firmware/python-miio for the classic models.
CONSUMABLE_MAX_SECONDS = {
    "main_brush": 300 * 60 * 60,
    "side_brush": 200 * 60 * 60,
    "filter": 150 * 60 * 60,
    "sensors": 30 * 60 * 60,
}


@dataclass
class DeviceIdentity:
    model: str
    firmware: str
    hardware: str
    ip_address: str
    mac_address: str
    wifi_ssid: str
    wifi_rssi: Optional[int]


class RoborockLocalClient:
    def __init__(
        self,
        ip_address: str,
        token: str,
        model: str = "auto",
        timeout: int = 5,
        debug_callback: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.ip_address = ip_address.strip()
        self.token = token.strip()
        self.configured_model = (model or "auto").strip()
        self.timeout = max(1, min(int(timeout), 30))
        self.debug_callback = debug_callback
        self.device: Optional[RoborockVacuum] = None
        self.identity: Optional[DeviceIdentity] = None
        self.fan_presets: dict[str, int] = {}
        self.crypto_backend = CRYPTO_BACKEND

    def _debug(self, message: str) -> None:
        if self.debug_callback is not None:
            self.debug_callback(message)

    def _create_vacuum(self, model: Optional[str]) -> RoborockVacuum:
        """Create RoborockVacuum across python-miio constructor variants.

        python-miio 0.5.12 does not accept a ``timeout`` keyword in every
        packaged build. Newer or distro-patched builds may accept it. We inspect
        the constructor and only pass supported keyword arguments. A guarded
        retry also handles wrappers whose signature cannot be inspected reliably.
        """
        kwargs: dict[str, Any] = {}
        try:
            parameters = inspect.signature(RoborockVacuum.__init__).parameters
        except (TypeError, ValueError):
            parameters = {}

        accepts_var_kwargs = any(
            parameter.kind == inspect.Parameter.VAR_KEYWORD
            for parameter in parameters.values()
        )

        if model and ("model" in parameters or accepts_var_kwargs):
            kwargs["model"] = model
        if "timeout" in parameters or accepts_var_kwargs:
            kwargs["timeout"] = self.timeout

        while True:
            try:
                device = RoborockVacuum(self.ip_address, self.token, **kwargs)

                # RoborockVacuum in python-miio 0.5.12 does not expose the
                # timeout argument, although the underlying MiIOProtocol does.
                # Apply the configured value after construction.
                try:
                    device._protocol._timeout = self.timeout
                except Exception:
                    pass

                # Keep the built-in retry behaviour, but avoid very long
                # blocking periods inside the Domoticz plugin thread.
                try:
                    device.retry_count = 2
                except Exception:
                    pass

                if "timeout" not in kwargs:
                    self._debug(
                        "Applied timeout directly to the python-miio protocol"
                    )
                return device
            except TypeError as exc:
                message = str(exc)
                removed = False
                for key in ("timeout", "model"):
                    if key in kwargs and (
                        "unexpected keyword argument '{}'".format(key) in message
                        or 'unexpected keyword argument "{}"'.format(key) in message
                    ):
                        kwargs.pop(key, None)
                        removed = True
                        self._debug(
                            "Retrying RoborockVacuum without unsupported '{}' argument".format(key)
                        )
                        break
                if not removed:
                    raise

    def connect(self) -> DeviceIdentity:
        self.device = None
        self.identity = None
        self.fan_presets = {}

        requested_model = None
        if self.configured_model.lower() not in ("", "auto", "detect"):
            requested_model = self.configured_model

        probe = self._create_vacuum(requested_model)
        info = probe.info()

        detected_model = str(getattr(info, "model", "") or requested_model or "")
        if not detected_model:
            detected_model = "roborock.vacuum.*"

        # Recreate the device with the detected model. This gives python-miio
        # the correct model-specific fan presets and optional capabilities.
        self.device = self._create_vacuum(detected_model)

        accesspoint = getattr(info, "accesspoint", {}) or {}
        wifi_ssid = str(accesspoint.get("ssid", "")) if isinstance(accesspoint, dict) else ""
        wifi_rssi_raw = accesspoint.get("rssi") if isinstance(accesspoint, dict) else None
        try:
            wifi_rssi = int(wifi_rssi_raw) if wifi_rssi_raw is not None else None
        except (TypeError, ValueError):
            wifi_rssi = None

        self.identity = DeviceIdentity(
            model=detected_model,
            firmware=str(getattr(info, "firmware_version", "") or ""),
            hardware=str(getattr(info, "hardware_version", "") or ""),
            ip_address=str(getattr(info, "ip_address", "") or self.ip_address),
            mac_address=str(getattr(info, "mac_address", "") or ""),
            wifi_ssid=wifi_ssid,
            wifi_rssi=wifi_rssi,
        )

        self.fan_presets = self._optional(
            "fan speed presets",
            self.device.fan_speed_presets,
            default={},
        ) or {}

        self._debug(
            "Connected to model {} with firmware {}".format(
                self.identity.model,
                self.identity.firmware or "unknown",
            )
        )
        return self.identity

    def _require_device(self) -> RoborockVacuum:
        if self.device is None:
            raise RuntimeError("Roborock client is not connected")
        return self.device

    def _optional(self, label: str, function: Callable[[], Any], default: Any = None) -> Any:
        try:
            return function()
        except Exception as exc:
            # Some legacy firmwares report unsupported commands as a generic
            # device error. Ignore only errors that explicitly identify an
            # unavailable method; real communication errors must propagate.
            message = str(exc).lower()
            unsupported_markers = (
                "unknown_method",
                "unknown method",
                "not supported",
                "unsupported",
                "method not found",
            )
            if any(marker in message for marker in unsupported_markers):
                self._debug("{} is not supported: {}".format(label, exc))
                return default
            raise

    @staticmethod
    def _seconds(value: Any) -> Optional[float]:
        if value is None:
            return None
        if isinstance(value, timedelta):
            return float(value.total_seconds())
        if hasattr(value, "total_seconds"):
            try:
                return float(value.total_seconds())
            except Exception:
                return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _percentage_from_remaining(remaining_seconds: Optional[float], maximum: int) -> Optional[float]:
        if remaining_seconds is None or maximum <= 0:
            return None
        return max(0.0, min(100.0, remaining_seconds * 100.0 / maximum))

    def refresh_protocol(self) -> None:
        """Recreate only the local protocol session.

        This forces a fresh miIO handshake without running model detection again.
        It is useful after a transient UDP timeout or when another client has
        communicated with the same vacuum.
        """
        model = None
        if self.identity is not None and self.identity.model:
            model = self.identity.model
        elif self.configured_model.lower() not in ("", "auto", "detect"):
            model = self.configured_model

        self.device = self._create_vacuum(model)
        self._debug("Roborock miIO protocol session recreated")

    def _status_reader(self) -> Callable[[], Any]:
        device = self._require_device()
        reader = getattr(device, "vacuum_status", None)
        if reader is None:
            reader = getattr(device, "status", None)
        if reader is None:
            raise AttributeError("Roborock status method is not available")
        return reader

    def read_status(self) -> dict[str, Any]:
        """Read the frequently changing state using a single miIO request.

        Earlier plugin versions made four requests every poll (status, fan,
        carpet and DND). The S5 status payload already contains the fan value and
        DND flag, so only the mandatory status call is used here. Slower settings
        are read one at a time by :meth:`read_auxiliary`.
        """
        status = self._status_reader()()
        raw = getattr(status, "data", {}) or {}
        if not isinstance(raw, dict):
            raw = {}

        fan_value = getattr(status, "fanspeed", None)
        if fan_value is None:
            fan_value = raw.get("fan_power")

        return {
            "state": str(getattr(status, "state", "Unknown")),
            "state_code": int(getattr(status, "state_code", 0) or 0),
            "battery": int(getattr(status, "battery", 0) or 0),
            "clean_area": float(getattr(status, "clean_area", 0.0) or 0.0),
            "clean_time_seconds": self._seconds(getattr(status, "clean_time", None)) or 0.0,
            "error": str(getattr(status, "error", "No error")),
            "error_code": int(getattr(status, "error_code", 0) or 0),
            "got_error": bool(getattr(status, "got_error", False)),
            "is_on": bool(getattr(status, "is_on", False)),
            "is_paused": bool(getattr(status, "is_paused", False)),
            "in_zone_cleaning": bool(getattr(status, "in_zone_cleaning", False)),
            "in_segment_cleaning": bool(getattr(status, "in_segment_cleaning", False)),
            "water_box_attached": getattr(status, "is_water_box_attached", None),
            "fan_value": int(fan_value) if fan_value is not None else None,
            "carpet_enabled": None,
            "carpet_parameters": None,
            # The status field `dnd_enabled` indicates the current DND state on
            # some S5 firmware, not whether the schedule itself is configured.
            # Read the schedule through dnd_status() on the auxiliary rotation.
            "dnd_enabled": None,
            "dnd_start": "",
            "dnd_end": "",
        }

    def read_auxiliary(self, section: str) -> dict[str, Any]:
        """Read one slower-changing section using one device request."""
        device = self._require_device()
        section = section.strip().lower()

        if section == "consumables":
            consumables = device.consumable_status()
            remaining_map = {
                "main_brush": self._seconds(getattr(consumables, "main_brush_left", None)),
                "side_brush": self._seconds(getattr(consumables, "side_brush_left", None)),
                "filter": self._seconds(getattr(consumables, "filter_left", None)),
                "sensors": self._seconds(getattr(consumables, "sensor_dirty_left", None)),
            }
            used_map = {
                "main_brush": self._seconds(getattr(consumables, "main_brush", None)),
                "side_brush": self._seconds(getattr(consumables, "side_brush", None)),
                "filter": self._seconds(getattr(consumables, "filter", None)),
                "sensors": self._seconds(getattr(consumables, "sensor_dirty", None)),
            }
            values: dict[str, Any] = {}
            for key in CONSUMABLE_MAX_SECONDS:
                values[key] = {
                    "remaining_seconds": remaining_map.get(key),
                    "used_seconds": used_map.get(key),
                    "remaining_percent": self._percentage_from_remaining(
                        remaining_map.get(key), CONSUMABLE_MAX_SECONDS[key]
                    ),
                }
            return {"consumables": values}

        if section == "history":
            history = device.clean_history()
            return {
                "history": {
                    "count": int(getattr(history, "count", 0) or 0),
                    "total_area": float(getattr(history, "total_area", 0.0) or 0.0),
                    "total_duration_seconds": self._seconds(
                        getattr(history, "total_duration", None)
                    ) or 0.0,
                }
            }

        if section == "last_clean":
            last_clean = device.last_clean_details()
            return {
                "last_clean": {
                    "start": getattr(last_clean, "start", None),
                    "end": getattr(last_clean, "end", None),
                    "duration_seconds": self._seconds(
                        getattr(last_clean, "duration", None)
                    ) or 0.0,
                    "area": float(getattr(last_clean, "area", 0.0) or 0.0),
                    "complete": bool(getattr(last_clean, "complete", False)),
                    "error": str(getattr(last_clean, "error", "No error")),
                    "error_code": int(getattr(last_clean, "error_code", 0) or 0),
                }
            }

        if section == "dnd":
            dnd = device.dnd_status()
            return {
                "dnd": {
                    "enabled": bool(getattr(dnd, "enabled", False)),
                    "start": str(getattr(dnd, "start", "")),
                    "end": str(getattr(dnd, "end", "")),
                }
            }

        if section == "carpet":
            carpet = device.carpet_mode()
            return {
                "carpet": {
                    "enabled": bool(getattr(carpet, "enabled", False)),
                    "parameters": {
                        "stall_time": getattr(carpet, "stall_time", None),
                        "low": getattr(carpet, "current_low", None),
                        "high": getattr(carpet, "current_high", None),
                        "integral": getattr(carpet, "current_integral", None),
                    },
                }
            }

        if section == "voice_volume":
            volume = device.sound_volume()
            return {"voice_volume": int(volume)}

        if section == "device_info":
            info = device.info(skip_cache=True)
            accesspoint = getattr(info, "accesspoint", {}) or {}
            wifi_ssid = ""
            wifi_rssi = None
            if isinstance(accesspoint, dict):
                wifi_ssid = str(accesspoint.get("ssid", "") or "")
                try:
                    wifi_rssi = int(accesspoint.get("rssi"))
                except (TypeError, ValueError):
                    wifi_rssi = None
            return {"wifi_rssi": wifi_rssi, "wifi_ssid": wifi_ssid}

        raise ValueError("Unknown auxiliary section: {}".format(section))

    def read_extended(self) -> dict[str, Any]:
        """Compatibility helper returning all auxiliary sections.

        New plugin versions call :meth:`read_auxiliary` one section at a time to
        avoid bursts of UDP requests. This method remains available for scripts.
        """
        result: dict[str, Any] = {}
        for section in (
            "consumables",
            "history",
            "last_clean",
            "dnd",
            "carpet",
            "voice_volume",
            "device_info",
        ):
            result.update(self.read_auxiliary(section))
        return result

    def command(self, action: str, value: Optional[int] = None) -> Any:
        device = self._require_device()
        action = action.strip().lower()

        actions: dict[str, Callable[[], Any]] = {
            "start": device.resume_or_start,
            "pause": device.pause,
            "stop": device.stop,
            "dock": device.home,
            "spot": device.spot,
            "find": device.find,
            "test_voice": device.test_sound_volume,
        }
        if action not in actions:
            raise ValueError("Unknown Roborock action: {}".format(action))
        return actions[action]()

    def set_fan_mode(self, preset_name: str) -> Any:
        device = self._require_device()
        if not self.fan_presets:
            self.fan_presets = device.fan_speed_presets()
        if preset_name not in self.fan_presets:
            raise ValueError(
                "Fan preset '{}' is not available. Available: {}".format(
                    preset_name,
                    ", ".join(self.fan_presets.keys()),
                )
            )
        return device.set_fan_speed(int(self.fan_presets[preset_name]))

    def set_carpet_boost(self, enabled: bool, current_parameters: Optional[dict[str, Any]] = None) -> Any:
        device = self._require_device()
        params = current_parameters or {}
        return device.set_carpet_mode(
            bool(enabled),
            stall_time=int(params.get("stall_time") or 10),
            low=int(params.get("low") or 400),
            high=int(params.get("high") or 500),
            integral=int(params.get("integral") or 450),
        )

    def set_dnd_enabled(
        self,
        enabled: bool,
        start_hour: int = 22,
        start_minute: int = 0,
        end_hour: int = 8,
        end_minute: int = 0,
    ) -> Any:
        device = self._require_device()
        if enabled:
            return device.set_dnd(start_hour, start_minute, end_hour, end_minute)
        return device.disable_dnd()

    def set_voice_volume(self, volume: int) -> Any:
        volume = max(0, min(int(volume), 100))
        return self._require_device().set_sound_volume(volume)

    def reset_consumable(self, consumable_key: str) -> Any:
        protocol_name = CONSUMABLE_PROTOCOL_NAMES.get(consumable_key)
        if protocol_name is None:
            raise ValueError("Unknown consumable: {}".format(consumable_key))
        # Using send directly keeps compatibility with python-miio versions
        # where the Consumable enum import path differs.
        return self._require_device().send("reset_consumable", [protocol_name])
