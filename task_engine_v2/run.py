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


def _get_default_adb_path() -> str:
    """
    Auto-detect adb path in both dev and packaged environments.

    Priority:
    1) Bundled adb in packaged output
    2) Bundled adb in build staging
    3) System adb from PATH
    """
    candidates: list[Path] = []

    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        candidates.extend(
            [
                exe_dir / "platform-tools" / "adb.exe",
                exe_dir / "_internal" / "platform-tools" / "adb.exe",
            ]
        )

        meipass = getattr(sys, "_MEIPASS", "")
        if meipass:
            base_path = Path(meipass)
            candidates.append(base_path / "platform-tools" / "adb.exe")

    cwd = Path.cwd()
    candidates.extend(
        [
            cwd / "build" / "staging" / "platform-tools" / "adb.exe",
            cwd / "task_engine_v2" / "platform-tools" / "adb.exe",
        ]
    )

    for path in candidates:
        if path.exists():
            return str(path)

    return "adb"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Independent task runner with multi-device support")
    parser.add_argument(
        "--assignments",
        default=_get_default_assignments_path(),
        help="Path to device assignment json (auto-detected in dev/packaged env)",
    )
    parser.add_argument("--adb-path", default=_get_default_adb_path(), help="adb executable path")
    parser.add_argument("--log-level", default="INFO", help="DEBUG/INFO/WARNING/ERROR")
    parser.add_argument(
        "--daily-reschedule-hour",
        type=int,
        default=7,
        help="Daily reschedule trigger hour in 24h format (default: 7)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    setup_logging(args.log_level)
    scheduler = DeviceTaskScheduler(
        assignments_file=args.assignments,
        adb_path=args.adb_path,
        daily_reschedule_hour=args.daily_reschedule_hour,
    )
    scheduler.run()


if __name__ == "__main__":
    main()
