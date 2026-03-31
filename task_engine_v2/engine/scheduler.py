from __future__ import annotations

from pathlib import Path
import logging
import threading
import subprocess
import time

from .models import load_assignments, load_task_config
from .task_runner import TaskRunner


logger = logging.getLogger(__name__)


class DeviceTaskScheduler:
    def __init__(self, assignments_file: str, adb_path: str = "adb") -> None:
        self.assignments_file = assignments_file
        self.adb_path = adb_path
        self.poll_interval_seconds = 3

    def run(self) -> None:
        assignments = load_assignments(self.assignments_file)
        if not assignments:
            logger.warning("no valid assignments found in %s", self.assignments_file)
            return

        exact_map: dict[str, str] = {}
        wildcard_task_files: list[str] = []
        assignments_path = Path(self.assignments_file).resolve()
        for assignment in assignments:
            if assignment.device_id:
                if assignment.device_id in exact_map:
                    logger.error("duplicated device assignment ignored | device=%s", assignment.device_id)
                    continue
                exact_map[assignment.device_id] = assignment.task_file
            else:
                wildcard_task_files.append(assignment.task_file)

        if len(wildcard_task_files) > 1:
            logger.warning("multiple wildcard assignments found; only the first one will be used")

        running_threads: dict[str, threading.Thread] = {}
        handled_devices: set[str] = set()

        logger.info("scheduler started | watch hot-plug devices enabled")
        try:
            while True:
                # Reap finished threads.
                finished = [device for device, thread in running_threads.items() if not thread.is_alive()]
                for device in finished:
                    running_threads.pop(device, None)

                for device in self._list_connected_devices():
                    if device in running_threads or device in handled_devices:
                        continue

                    task_file_str = self._resolve_task_file_for_device(
                        device_id=device,
                        exact_map=exact_map,
                        wildcard_task_files=wildcard_task_files,
                    )
                    if not task_file_str:
                        continue

                    task_file = Path(task_file_str)
                    if not task_file.is_absolute():
                        task_file = (assignments_path.parent / task_file).resolve()

                    task = load_task_config(task_file)
                    runner = TaskRunner(device_id=device, task=task, adb_path=self.adb_path)
                    thread = threading.Thread(target=runner.run, name=f"task-{device}", daemon=False)
                    thread.start()

                    running_threads[device] = thread
                    handled_devices.add(device)
                    logger.info("task scheduled | device=%s | task=%s", device, task.name)

                time.sleep(self.poll_interval_seconds)
        except KeyboardInterrupt:
            logger.info("scheduler interrupted, waiting running tasks to finish")

        for thread in running_threads.values():
            thread.join()

    def _resolve_task_file_for_device(
        self,
        device_id: str,
        exact_map: dict[str, str],
        wildcard_task_files: list[str],
    ) -> str:
        if device_id in exact_map:
            return exact_map[device_id]
        if wildcard_task_files:
            return wildcard_task_files[0]
        return ""

    def _list_connected_devices(self) -> list[str]:
        cmd = [self.adb_path, "devices"]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=15,
                encoding="utf-8",
                errors="ignore",
            )
        except Exception as exc:
            logger.error("failed to list adb devices: %s", exc)
            return []

        if result.returncode != 0:
            logger.error("adb devices failed: %s", (result.stderr or "").strip())
            return []

        devices: list[str] = []
        for line in (result.stdout or "").splitlines():
            line = line.strip()
            if not line or line.startswith("List of devices attached"):
                continue
            parts = line.split()
            if len(parts) >= 2 and parts[1] == "device":
                devices.append(parts[0])
        return devices
