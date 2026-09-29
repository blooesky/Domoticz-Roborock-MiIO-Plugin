#!/usr/bin/env python3
"""Read-only, token-redacted diagnostic for legacy Roborock miIO devices."""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import enum
import inspect
import ipaddress
import inspect
import json
import platform
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Callable


REDACTED = "[REDACTED]"


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only capability diagnostic for legacy Roborock vacuums."
    )
    parser.add_argument("--ip", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--model", default="auto")
    parser.add_argument("--timeout", type=int, default=5)
    parser.add_argument("--output", default="diagnostic_result.json")
    parser.add_argument("--extended", action="store_true")
    return parser.parse_args()


def validate_arguments(args: argparse.Namespace) -> None:
    try:
        ipaddress.ip_address(args.ip)
    except ValueError as exc:
        raise SystemExit("Invalid IP address: {}".format(args.ip)) from exc
    if len(args.token.strip()) != 32:
        raise SystemExit("Token must contain 32 hexadecimal characters.")
    try:
        int(args.token.strip(), 16)
    except ValueError as exc:
        raise SystemExit("Token must contain only hexadecimal characters.") from exc


def redact_text(value: str, token: str) -> str:
    result = value.replace(token, REDACTED)
    # DeviceInfo may expose the token in upper/lower case.
    result = result.replace(token.lower(), REDACTED)
    result = result.replace(token.upper(), REDACTED)
    return result


def normalise(value: Any, token: str, depth: int = 0) -> Any:
    if depth > 8:
        return redact_text(repr(value), token)

    if value is None or isinstance(value, (int, float, bool)):
        return value
    if isinstance(value, str):
        return redact_text(value, token)
    if isinstance(value, enum.Enum):
        return {"name": value.name, "value": normalise(value.value, token, depth + 1)}
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return value.isoformat()
    if isinstance(value, dt.timedelta):
        return {"seconds": value.total_seconds(), "display": str(value)}
    if dataclasses.is_dataclass(value):
        return normalise(dataclasses.asdict(value), token, depth + 1)
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            key_text = str(key)
            if "token" in key_text.lower():
                result[key_text] = REDACTED
            else:
                result[key_text] = normalise(item, token, depth + 1)
        return result
    if isinstance(value, (list, tuple, set, frozenset)):
        return [normalise(item, token, depth + 1) for item in value]

    properties = {}
    for name, descriptor in inspect.getmembers(type(value)):
        if not isinstance(descriptor, property) or name.startswith("_"):
            continue
        if "token" in name.lower():
            properties[name] = REDACTED
            continue
        try:
            properties[name] = normalise(getattr(value, name), token, depth + 1)
        except Exception as exc:
            properties[name] = {"_property_error": "{}: {}".format(type(exc).__name__, exc)}

    raw = None
    for attribute in ("data", "_data", "raw", "_raw"):
        try:
            candidate = getattr(value, attribute)
        except Exception:
            continue
        if isinstance(candidate, (dict, list, tuple)):
            raw = normalise(candidate, token, depth + 1)
            break

    result = {"_type": type(value).__name__}
    if raw is not None:
        result["raw"] = raw
    if properties:
        result["properties"] = properties
    result["display"] = redact_text(str(value), token)
    return result


def run_query(
    name: str,
    description: str,
    function: Callable[[], Any],
    token: str,
) -> dict[str, Any]:
    print("\n[{}] {}".format(name, description))
    started = time.monotonic()
    try:
        result = function()
        elapsed = round(time.monotonic() - started, 3)
        safe_result = normalise(result, token)
        print("OK ({}s)".format(elapsed))
        print(json.dumps(safe_result, ensure_ascii=False, indent=2, default=str))
        return {"supported": True, "elapsed_seconds": elapsed, "result": safe_result}
    except Exception as exc:
        elapsed = round(time.monotonic() - started, 3)
        message = "{}: {}".format(type(exc).__name__, redact_text(str(exc), token))
        print("NOT AVAILABLE / ERROR ({}s): {}".format(elapsed, message))
        return {
            "supported": False,
            "elapsed_seconds": elapsed,
            "error": message,
            "traceback": redact_text(traceback.format_exc(), token),
        }


def main() -> int:
    args = parse_arguments()
    validate_arguments(args)
    token = args.token.strip()

    try:
        from miio_crypto_compat import CRYPTO_BACKEND, install_miio_crypto_patch

        install_miio_crypto_patch()

        import miio
        from miio import RoborockVacuum
    except Exception as exc:
        print("ERROR: python-miio could not be imported: {}".format(exc), file=sys.stderr)
        return 2

    requested_model = None if args.model.lower() in ("auto", "detect", "") else args.model
    constructor_kwargs = {}
    try:
        constructor_parameters = inspect.signature(RoborockVacuum.__init__).parameters
    except (TypeError, ValueError):
        constructor_parameters = {}
    accepts_var_kwargs = any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in constructor_parameters.values()
    )
    if requested_model and ("model" in constructor_parameters or accepts_var_kwargs):
        constructor_kwargs["model"] = requested_model
    if "timeout" in constructor_parameters or accepts_var_kwargs:
        constructor_kwargs["timeout"] = max(1, min(args.timeout, 30))

    while True:
        try:
            vacuum = RoborockVacuum(args.ip, token, **constructor_kwargs)
            break
        except TypeError as exc:
            message = str(exc)
            removed = False
            for key in ("timeout", "model"):
                if key in constructor_kwargs and "unexpected keyword argument" in message and key in message:
                    constructor_kwargs.pop(key, None)
                    removed = True
                    break
            if not removed:
                raise

    print("=" * 72)
    print("ROBOROCK LEGACY LOCAL READ-ONLY DIAGNOSTIC")
    print("=" * 72)
    print("Python: {}".format(platform.python_version()))
    print("python-miio: {}".format(getattr(miio, "__version__", "unknown")))
    print("miIO crypto backend: {}".format(CRYPTO_BACKEND))
    print("IP: {}".format(args.ip))
    print("Model requested: {}".format(args.model))
    print("Token: {}".format(REDACTED))
    print("No control commands will be sent.")

    status_reader = getattr(vacuum, "vacuum_status", None)
    if status_reader is None:
        status_reader = vacuum.status

    queries = [
        ("device_info", "Model, firmware, hardware and network information", vacuum.info),
        ("vacuum_status", "Current status, battery, area, time and errors", status_reader),
        ("fan_speed", "Current fan power value", vacuum.fan_speed),
        ("fan_speed_presets", "Available fan presets", vacuum.fan_speed_presets),
        ("consumables", "Brush, filter and sensor usage", vacuum.consumable_status),
        ("clean_history", "Total cleaning statistics", vacuum.clean_history),
        ("last_clean", "Most recent cleaning session", vacuum.last_clean_details),
        ("dnd", "Do Not Disturb schedule", vacuum.dnd_status),
        ("carpet_mode", "Carpet boost settings", vacuum.carpet_mode),
        ("room_mapping", "Saved room/segment identifiers", vacuum.get_room_mapping),
    ]

    if args.extended:
        queries.extend(
            [
                ("timers", "Internal vacuum schedules", vacuum.timer),
                ("sound_info", "Installed voice information", vacuum.sound_info),
                ("sound_volume", "Voice volume", vacuum.sound_volume),
                ("serial_number", "Serial number", vacuum.serial_number),
                ("locale", "Locale settings", vacuum.locale),
                ("timezone", "Vacuum timezone", vacuum.timezone),
                ("firmware_features", "Firmware feature identifiers", vacuum.firmware_features),
            ]
        )

    results = {}
    for name, description, function in queries:
        results[name] = run_query(name, description, function, token)

    successful = sum(1 for item in results.values() if item["supported"])
    failed = len(results) - successful
    report = {
        "diagnostic": {
            "created_at": dt.datetime.now().astimezone().isoformat(),
            "read_only": True,
            "ip": args.ip,
            "model_requested": args.model,
            "token": REDACTED,
            "python_version": platform.python_version(),
            "python_miio_version": getattr(miio, "__version__", "unknown"),
            "successful_queries": successful,
            "failed_or_unsupported_queries": failed,
        },
        "results": results,
    }

    output_path = Path(args.output).expanduser().resolve()
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    print("\n" + "=" * 72)
    print("Completed: {} successful, {} unavailable/failed.".format(successful, failed))
    print("Result saved to: {}".format(output_path))
    print("The token has been fully removed from console output and JSON.")
    print("=" * 72)
    return 0 if successful else 3


if __name__ == "__main__":
    raise SystemExit(main())
