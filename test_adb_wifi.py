import argparse
import json
import os
import time
from typing import Any, Dict, List

import adb_util
from screenwatcher.config_service import ConfigError, ConfigService


def _build_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Test ADB Wi-Fi connectivity and screenshot capability for configured wireless devices."
    )
    parser.add_argument(
        "--adb-path",
        default="",
        help="Override adb executable path. If omitted, use settings_config.json -> adb_path.",
    )
    parser.add_argument(
        "--output-dir",
        default="wifi_test_screenshots",
        help="Directory to save test screenshots.",
    )
    parser.add_argument(
        "--save-json",
        default="adb_wifi_report.json",
        help="Path to save the Wi-Fi test report JSON. Default: adb_wifi_report.json",
    )
    parser.add_argument(
        "--cleanup",
        action="store_true",
        help="Delete screenshots after each test if capture succeeds.",
    )
    return parser.parse_args()


def _load_settings() -> Dict[str, Any]:
    service = ConfigService()
    try:
        return service.load_settings()
    except ConfigError as exc:
        print(f"[WARN] Failed to load settings_config.json: {exc}")
        return {
            "adb_path": "adb",
            "adb_wifi_devices": [],
        }


def _ensure_dir(path: str) -> None:
    if not os.path.exists(path):
        os.makedirs(path)


def _test_wifi_device(adb_path: str, serial: str, output_dir: str, cleanup: bool) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "serial": serial,
        "connect_success": False,
        "listed_after_connect": False,
        "foreground_app": "",
        "current_activity": "",
        "screenshot_success": False,
        "screenshot_path": "",
        "error": "",
    }

    connect_success = adb_util.connect_wifi_device(adb_path, serial)
    result["connect_success"] = connect_success

    connected_devices = adb_util.get_connected_devices(adb_path)
    result["listed_after_connect"] = serial in connected_devices

    if not connect_success and not result["listed_after_connect"]:
        result["error"] = "connect_failed"
        return result

    try:
        result["foreground_app"] = adb_util.get_foreground_app(adb_path, serial)
        result["current_activity"] = adb_util.get_current_activity(adb_path, serial)
    except Exception as exc:
        result["error"] = f"device_query_failed: {exc}"

    timestamp = int(time.time())
    screenshot_path = os.path.join(output_dir, f"{serial.replace(':', '_')}_{timestamp}.png")
    result["screenshot_path"] = screenshot_path

    screenshot_success = adb_util.take_screenshot(adb_path, serial, screenshot_path)
    result["screenshot_success"] = screenshot_success

    if screenshot_success and cleanup and os.path.exists(screenshot_path):
        os.remove(screenshot_path)
        result["screenshot_path"] = ""

    if not screenshot_success and not result["error"]:
        result["error"] = "screenshot_failed"

    return result


def main() -> None:
    args = _build_args()
    settings = _load_settings()

    adb_path = args.adb_path or settings.get("adb_path", "adb")
    wifi_devices = settings.get("adb_wifi_devices", [])

    if not wifi_devices:
        print("No adb_wifi_devices configured in settings_config.json.")
        return

    _ensure_dir(args.output_dir)

    print(f"Configured Wi-Fi devices ({len(wifi_devices)}): {[item.get('serial', '') for item in wifi_devices]}")

    results: List[Dict[str, Any]] = []
    for item in wifi_devices:
        serial = str(item.get("serial", "")).strip()
        auto_connect = bool(item.get("auto_connect", True))
        if not serial:
            continue

        print(f"\n=== Testing Wi-Fi device: {serial} | auto_connect={auto_connect} ===")
        if not auto_connect:
            print("Skip connect because auto_connect=false")
            results.append(
                {
                    "serial": serial,
                    "connect_success": False,
                    "listed_after_connect": serial in adb_util.get_connected_devices(adb_path),
                    "foreground_app": "",
                    "current_activity": "",
                    "screenshot_success": False,
                    "screenshot_path": "",
                    "error": "auto_connect_disabled",
                }
            )
            continue

        result = _test_wifi_device(adb_path, serial, args.output_dir, args.cleanup)
        results.append(result)

        print(f"connect_success: {result['connect_success']}")
        print(f"listed_after_connect: {result['listed_after_connect']}")
        print(f"foreground_app: {result['foreground_app'] or '(empty)'}")
        print(f"current_activity: {result['current_activity'] or '(empty)'}")
        print(f"screenshot_success: {result['screenshot_success']}")
        if result["screenshot_path"]:
            print(f"screenshot_path: {result['screenshot_path']}")
        if result["error"]:
            print(f"error: {result['error']}")

    with open(args.save_json, "w", encoding="utf-8") as file:
        json.dump(results, file, ensure_ascii=False, indent=2)

    success_count = sum(1 for item in results if item.get("connect_success") and item.get("screenshot_success"))
    print(f"\nDone. full_success={success_count}/{len(results)}")
    print(f"Saved Wi-Fi report: {args.save_json}")


if __name__ == "__main__":
    main()
