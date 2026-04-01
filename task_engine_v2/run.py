from __future__ import annotations

import argparse

from engine.logging_util import setup_logging
from engine.scheduler import DeviceTaskScheduler


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Independent task runner with multi-device support")
    parser.add_argument(
        "--assignments",
        default="task_engine_v2/configs/devices.json",
        help="Path to device assignment json (default: task_engine_v2/configs/devices.json)",
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
