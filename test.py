import argparse
import asyncio
import json
import os
import time
from typing import Any, Dict, List

import adb_util
import util
from screenwatcher.config_service import ConfigError, ConfigService


def _build_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Capture screenshots from all connected devices and OCR all detected text."
    )
    parser.add_argument(
        "--adb-path",
        default="",
        help="Override adb executable path. If omitted, use settings_config.json -> adb_path.",
    )
    parser.add_argument(
        "--output-dir",
        default="",
        help="Override screenshot output directory. If omitted, use settings_config.json -> screenshot_dir.",
    )
    parser.add_argument(
        "--no-keep-screenshots",
        action="store_true",
        help="Do not keep captured screenshots after OCR.",
    )
    parser.add_argument(
        "--max-lines",
        type=int,
        default=0,
        help="Max OCR lines printed per device. <= 0 means no limit.",
    )
    parser.add_argument(
        "--save-json",
        default="ocr_report.json",
        help="Path to save OCR result JSON. Default: ocr_report.json",
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
            "screenshot_dir": "temp_screenshots",
        }


def _ensure_dir(path: str) -> None:
    if not os.path.exists(path):
        os.makedirs(path)


async def _ocr_device(
    adb_path: str,
    output_dir: str,
    device_id: str,
    keep_screenshots: bool,
    max_lines: int,
) -> Dict[str, Any]:
    timestamp = int(time.time())
    safe_device_id = device_id.replace(":", "_")
    screenshot_path = os.path.join(output_dir, f"{safe_device_id}_{timestamp}.png")

    result: Dict[str, Any] = {
        "device": device_id,
        "screenshot": screenshot_path,
        "success": False,
        "line_count": 0,
        "lines": [],
        "error": "",
    }

    if not adb_util.take_screenshot(adb_path, device_id, screenshot_path):
        result["error"] = "screenshot_failed"
        return result

    try:
        lines = await util.get_all_text_from_image(screenshot_path)
        result["success"] = True
        result["line_count"] = len(lines)
        result["lines"] = [
            {
                "text": item.get("text", ""),
                "box": list(item.get("box", (0, 0, 0, 0))),
            }
            for item in lines
        ]

        print(f"\n=== Device: {device_id} | OCR lines: {len(lines)} ===")
        if not lines:
            print("(no text detected)")
        else:
            display_count = len(lines) if max_lines <= 0 else min(max_lines, len(lines))
            for i in range(display_count):
                item = lines[i]
                print(f"{i + 1:03d}. {item['text']} | box={item['box']}")
            if max_lines > 0 and len(lines) > display_count:
                print(f"... truncated {len(lines) - display_count} lines")

    except Exception as exc:  # defensive: OCR runtime can fail on malformed image
        result["error"] = str(exc)
        print(f"[ERROR] OCR failed on {device_id}: {exc}")

    finally:
        if not keep_screenshots and os.path.exists(screenshot_path):
            os.remove(screenshot_path)

    return result


async def main() -> None:
    args = _build_args()
    settings = _load_settings()

    adb_path = args.adb_path or settings.get("adb_path", "adb")
    output_dir = args.output_dir or settings.get("screenshot_dir", "temp_screenshots")
    max_lines = int(args.max_lines)
    keep_screenshots = not args.no_keep_screenshots

    _ensure_dir(output_dir)

    adb_util.ensure_wifi_devices_connected(adb_path, settings.get("adb_wifi_devices", []))
    devices = adb_util.get_connected_devices(adb_path)
    if not devices:
        print("No connected devices found.")
        return

    print(f"Connected devices ({len(devices)}): {devices}")

    results: List[Dict[str, Any]] = []
    for device_id in devices:
        result = await _ocr_device(
            adb_path=adb_path,
            output_dir=output_dir,
            device_id=device_id,
            keep_screenshots=keep_screenshots,
            max_lines=max_lines,
        )
        results.append(result)

    success_count = sum(1 for item in results if item.get("success"))
    print(f"\nDone. success={success_count}/{len(results)}")

    with open(args.save_json, "w", encoding="utf-8") as file:
        json.dump(results, file, ensure_ascii=False, indent=2)
    print(f"Saved OCR report: {args.save_json}")


if __name__ == "__main__":
    asyncio.run(main())
