from __future__ import annotations

import argparse
import sys
from pathlib import Path

from engine.logging_util import setup_logging
from engine.scheduler import DeviceTaskScheduler


def _get_default_assignments_path() -> str:
    """
    Auto-detect default devices.json path in both dev and packaged environments.
    
    - Packaged (PyInstaller): checks _internal/defaults/devices.json
    - Development: checks task_engine_v2/configs/devices.json
    """
    candidates = []
    
    # PyInstaller packaged environment
    if getattr(sys, "frozen", False):
        base_path = Path(sys._MEIPASS)
        candidates.append(base_path / "defaults" / "devices.json")
    
    # Development environment
    candidates.append(Path("task_engine_v2/configs/devices.json"))
    candidates.append(Path.cwd() / "task_engine_v2/configs/devices.json")
    
    for path in candidates:
        if path.exists():
            return str(path)
    
    # Fallback: return first candidate (will error properly if file missing)
    return str(candidates[0] if candidates else "task_engine_v2/configs/devices.json")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Independent task runner with multi-device support")
    parser.add_argument(
        "--assignments",
        default=_get_default_assignments_path(),
        help="Path to device assignment json (auto-detected in dev/packaged env)",
    )
    parser.add_argument("--adb-path", default="adb", help="adb executable path")
    parser.add_argument("--log-level", default="INFO", help="DEBUG/INFO/WARNING/ERROR")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    setup_logging(args.log_level)
    scheduler = DeviceTaskScheduler(assignments_file=args.assignments, adb_path=args.adb_path)
    scheduler.run()


if __name__ == "__main__":
    main()
