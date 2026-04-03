from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
import logging
import threading
import subprocess
import time

from .models import DeviceAssignment, WifiDeviceConfig, load_task_config, load_task_list, load_wifi_devices
from .adb_client import ADBClient
from .task_runner import TaskRunner


logger = logging.getLogger(__name__)


class DeviceTaskScheduler:
    def __init__(self, devices_file: str, task_list_file: str, adb_path: str = "adb", daily_reschedule_hour: int = 7) -> None:
        self.devices_file = devices_file
        self.task_list_file = task_list_file
        self.adb_path = adb_path
        self.poll_interval_seconds = 3
        self.low_activity_poll_interval_seconds = 5
        self.wifi_poll_interval_seconds = 12
        self.daily_reschedule_hour = max(0, min(23, int(daily_reschedule_hour)))
        # config_serial -> last successfully resolved serial (may differ after port drift)
        self._wifi_resolved: dict[str, str] = {}
        self._wifi_stop_event = threading.Event()
        self._wifi_devices: list[WifiDeviceConfig] = []
        self._wifi_devices_lock = threading.Lock()
        self._last_daily_reschedule_date: date | None = None
        self._allowed_windows: list[tuple[int, int]] = []
        self._low_activity_mode = False

    def run(self) -> None:
        devices_path = Path(self.devices_file).resolve()
        task_list_path = Path(self.task_list_file).resolve()
        assignments, wifi_devices = self._load_schedule_config(
            devices_path=devices_path,
            task_list_path=task_list_path,
            log_missing_wifi=True,
        )
        if not assignments:
            logger.warning("no valid assignments found in %s", self.task_list_file)
            return

        self._set_wifi_devices(wifi_devices)
        config_revision = self._build_config_revision(devices_path, task_list_path, assignments)
        self._allowed_windows = self._build_allowed_windows(assignments)

        running_threads: dict[str, threading.Thread] = {}
        stop_events: dict[str, threading.Event] = {}
        handled_generation: dict[str, int] = {}
        schedule_generation = 0
        wifi_thread: threading.Thread | None = None

        now = datetime.now()
        if now.hour >= self.daily_reschedule_hour:
            self._last_daily_reschedule_date = now.date()

        if wifi_devices:
            logger.info("scheduler connecting wifi devices | count=%s", len(wifi_devices))
            wifi_thread = threading.Thread(
                target=self._wifi_connect_loop,
                name="wifi-connect-loop",
                daemon=True,
            )
            wifi_thread.start()

        logger.info(
            "scheduler started | watch hot-plug devices enabled | daily_reschedule_hour=%s",
            self.daily_reschedule_hour,
        )
        try:
            while True:
                updated_assignments, updated_wifi, updated_revision = self._reload_config_if_changed(
                    devices_path=devices_path,
                    task_list_path=task_list_path,
                    current_revision=config_revision,
                )
                if updated_revision != config_revision:
                    config_revision = updated_revision
                    assignments = updated_assignments
                    self._allowed_windows = self._build_allowed_windows(assignments)
                    self._set_wifi_devices(updated_wifi)
                    if updated_wifi and (wifi_thread is None or not wifi_thread.is_alive()):
                        logger.info("scheduler starting wifi-connect-loop from config update | count=%s", len(updated_wifi))
                        wifi_thread = threading.Thread(
                            target=self._wifi_connect_loop,
                            name="wifi-connect-loop",
                            daemon=True,
                        )
                        wifi_thread.start()
                    schedule_generation += 1
                    logger.info(
                        "scheduler generation advanced by config update | generation=%s | assignments=%s | wifi_devices=%s",
                        schedule_generation,
                        len(assignments),
                        len(updated_wifi),
                    )

                if self._should_daily_reschedule():
                    schedule_generation += 1
                    logger.info(
                        "scheduler generation advanced by daily trigger | generation=%s | trigger_hour=%s",
                        schedule_generation,
                        self.daily_reschedule_hour,
                    )

                # Reap finished threads.
                finished = [device for device, thread in running_threads.items() if not thread.is_alive()]
                for device in finished:
                    running_threads.pop(device, None)
                    stop_events.pop(device, None)

                connected_devices = set(self._list_connected_devices())

                if self._all_tasks_disallowed_now():
                    if not self._low_activity_mode:
                        logger.info(
                            "scheduler enter low-activity mode | all tasks out of allowed hours | sleep=%ss",
                            self.low_activity_poll_interval_seconds,
                        )
                    self._low_activity_mode = True
                    # Stop all active device task threads when outside allowed windows.
                    for device, event in stop_events.items():
                        if not event.is_set():
                            logger.info("scheduler stopping task thread by time window | device=%s", device)
                            event.set()
                else:
                    if self._low_activity_mode:
                        self._low_activity_mode = False
                        schedule_generation += 1
                        logger.info(
                            "scheduler exit low-activity mode | generation=%s | resume scheduling",
                            schedule_generation,
                        )

                # A disconnected device should be eligible for a fresh schedule after reconnect.
                handled_generation = {
                    device: generation
                    for device, generation in handled_generation.items()
                    if device in connected_devices
                }

                for device in connected_devices:
                    if self._low_activity_mode:
                        continue
                    if device in running_threads:
                        continue
                    if handled_generation.get(device, -1) >= schedule_generation:
                        continue

                    matched_assignments = self._resolve_assignments_for_device(
                        device_id=device,
                        assignments=assignments,
                    )
                    if not matched_assignments:
                        continue

                    adb = ADBClient(device_id=device, adb_path=self.adb_path)
                    mute_ok = adb.ensure_muted()
                    brightness_ok = adb.ensure_min_brightness()
                    logger.info(
                        "device connected, pre-actions applied | device=%s | mute_ok=%s | min_brightness_ok=%s",
                        device,
                        mute_ok,
                        brightness_ok,
                    )

                    stop_event = threading.Event()
                    thread = threading.Thread(
                        target=self._run_task_chain_for_device,
                        args=(device, matched_assignments, task_list_path, stop_event),
                        name=f"task-chain-{device}",
                        daemon=False,
                    )
                    thread.start()

                    running_threads[device] = thread
                    stop_events[device] = stop_event
                    handled_generation[device] = schedule_generation
                    logger.info(
                        "task chain scheduled | device=%s | count=%s | generation=%s",
                        device,
                        len(matched_assignments),
                        schedule_generation,
                    )
                sleep_seconds = (
                    self.low_activity_poll_interval_seconds
                    if self._low_activity_mode
                    else self.poll_interval_seconds
                )
                time.sleep(sleep_seconds)
        except KeyboardInterrupt:
            logger.info("scheduler interrupted, waiting running tasks to finish")
        finally:
            self._wifi_stop_event.set()
            if wifi_thread and wifi_thread.is_alive():
                wifi_thread.join(timeout=2)

        for event in stop_events.values():
            event.set()
        for thread in running_threads.values():
            thread.join()

    def _resolve_assignments_for_device(
        self,
        device_id: str,
        assignments: list[DeviceAssignment],
    ) -> list[DeviceAssignment]:
        matched: list[DeviceAssignment] = []
        for assignment in assignments:
            if not assignment.device_id or assignment.device_id == device_id:
                matched.append(assignment)
        return matched

    def _run_task_chain_for_device(
        self,
        device_id: str,
        assignments: list[DeviceAssignment],
        task_list_path: Path,
        stop_event: threading.Event,
    ) -> None:
        if not assignments:
            return

        loop_assignments = [item for item in assignments if item.need_loop]

        for index, assignment in enumerate(assignments, start=1):
            if stop_event.is_set():
                logger.info("task chain stop by scheduler signal | device=%s", device_id)
                return
            if not self._is_device_connected(device_id):
                logger.warning("task chain stop because device disconnected | device=%s", device_id)
                return
            self._run_single_assignment(
                device_id=device_id,
                assignment=assignment,
                task_list_path=task_list_path,
                index=index,
                total=len(assignments),
                stop_event=stop_event,
            )

        if not loop_assignments:
            return

        logger.info("task chain entering loop mode | device=%s | loop_count=%s", device_id, len(loop_assignments))
        loop_index = 0
        while True:
            if stop_event.is_set():
                logger.info("task chain loop stop by scheduler signal | device=%s", device_id)
                return
            if not self._is_device_connected(device_id):
                logger.warning("task chain loop stopped because device disconnected | device=%s", device_id)
                return
            assignment = loop_assignments[loop_index]
            self._run_single_assignment(
                device_id=device_id,
                assignment=assignment,
                task_list_path=task_list_path,
                index=loop_index + 1,
                total=len(loop_assignments),
                loop_mode=True,
                stop_event=stop_event,
            )
            loop_index = (loop_index + 1) % len(loop_assignments)

    def _run_single_assignment(
        self,
        device_id: str,
        assignment: DeviceAssignment,
        task_list_path: Path,
        index: int,
        total: int,
        loop_mode: bool = False,
        stop_event: threading.Event | None = None,
    ) -> None:
        task_file = Path(assignment.task_file)
        if not task_file.is_absolute():
            task_file = (task_list_path.parent / task_file).resolve()

        task = load_task_config(task_file)
        # Unified time-window control comes from task_list.json assignment entry.
        task.execute.allow_start_hour = assignment.allow_start_hour
        task.execute.allow_end_hour = assignment.allow_end_hour
        logger.info(
            "task chain start item | device=%s | index=%s/%s | loop_mode=%s | need_loop=%s | task=%s",
            device_id,
            index,
            total,
            loop_mode,
            assignment.need_loop,
            task.name,
        )

        runner = TaskRunner(
            device_id=device_id,
            task=task,
            adb_path=self.adb_path,
            should_stop=stop_event.is_set if stop_event else None,
        )
        runner.run()

        logger.info(
            "task chain finished item | device=%s | index=%s/%s | loop_mode=%s | need_loop=%s | task=%s",
            device_id,
            index,
            total,
            loop_mode,
            assignment.need_loop,
            task.name,
        )

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

    def _is_device_connected(self, device_id: str) -> bool:
        return device_id in self._list_connected_devices()

    @staticmethod
    def _wifi_host(serial: str) -> str:
        """Extract the IP/host part from host:port or bare host."""
        return serial.split(":", 1)[0] if ":" in serial else serial

    def _connect_wifi_devices(self, wifi_devices: list[WifiDeviceConfig]) -> None:
        connected = set(self._list_connected_devices())
        # Build a host -> active-serial mapping from currently connected devices
        connected_by_host: dict[str, str] = {}
        for s in connected:
            connected_by_host[self._wifi_host(s)] = s

        for cfg in wifi_devices:
            if not cfg.auto_connect:
                continue

            host = self._wifi_host(cfg.serial)

            # Check if the device is already online (possibly with a different port)
            if host in connected_by_host:
                active_serial = connected_by_host[host]
                prev_resolved = self._wifi_resolved.get(cfg.serial, cfg.serial)
                if active_serial != prev_resolved:
                    logger.info(
                        "wifi device port changed | config=%s | old=%s | new=%s",
                        cfg.serial, prev_resolved, active_serial,
                    )
                    self._wifi_resolved[cfg.serial] = active_serial
                continue

            # Device is not online — attempt connection with port-drift recovery
            # Use last known resolved serial as the starting hint so the direct
            # connect attempt is more likely to succeed after a port change.
            hint_serial = self._wifi_resolved.get(cfg.serial, cfg.serial)
            resolved = ADBClient.wifi_connect_with_recovery(hint_serial, self.adb_path)
            if resolved:
                if resolved != cfg.serial:
                    logger.info(
                        "wifi device connected with port recovery | config=%s | resolved=%s",
                        cfg.serial, resolved,
                    )
                else:
                    logger.info("wifi device connected | serial=%s", resolved)
                self._wifi_resolved[cfg.serial] = resolved
            else:
                logger.warning("wifi device connect failed | serial=%s", cfg.serial)

    def _wifi_connect_loop(self) -> None:
        # Run one immediate attempt, then periodic retries in background.
        while not self._wifi_stop_event.is_set():
            try:
                self._connect_wifi_devices(self._get_wifi_devices_snapshot())
            except Exception:
                logger.exception("wifi connect loop failed")
            if self._wifi_stop_event.wait(self.wifi_poll_interval_seconds):
                break

    def _load_schedule_config(
        self,
        devices_path: Path,
        task_list_path: Path,
        log_missing_wifi: bool,
    ) -> tuple[list[DeviceAssignment], list[WifiDeviceConfig]]:
        assignments = load_task_list(task_list_path)

        wifi_devices = load_wifi_devices(devices_path)
        if not wifi_devices and log_missing_wifi:
            logger.warning(
                "no wifi devices configured in %s (supported keys: wifi_devices, adb_wifi_devices)",
                devices_path.name,
            )

        return assignments, wifi_devices

    def _build_config_revision(self, devices_path: Path, task_list_path: Path, assignments: list[DeviceAssignment]) -> str:
        parts: list[str] = []
        paths: list[Path] = [devices_path, task_list_path]
        for item in assignments:
            task_file = Path(item.task_file)
            if not task_file.is_absolute():
                task_file = (task_list_path.parent / task_file).resolve()
            paths.append(task_file)

        seen: set[Path] = set()
        for path in paths:
            if path in seen:
                continue
            seen.add(path)
            if path.exists():
                stat = path.stat()
                parts.append(f"{path}:{stat.st_mtime_ns}:{stat.st_size}")
            else:
                parts.append(f"{path}:missing")
        return "|".join(parts)

    def _reload_config_if_changed(
        self,
        devices_path: Path,
        task_list_path: Path,
        current_revision: str,
    ) -> tuple[list[DeviceAssignment], list[WifiDeviceConfig], str]:
        assignments, wifi_devices = self._load_schedule_config(
            devices_path=devices_path,
            task_list_path=task_list_path,
            log_missing_wifi=False,
        )
        if not assignments:
            logger.warning("skip empty assignments on reload | file=%s", task_list_path)
            return [], self._get_wifi_devices_snapshot(), current_revision

        revision = self._build_config_revision(devices_path, task_list_path, assignments)
        if revision == current_revision:
            return assignments, wifi_devices, current_revision
        return assignments, wifi_devices, revision

    def _should_daily_reschedule(self) -> bool:
        now = datetime.now()
        today = now.date()
        if now.hour < self.daily_reschedule_hour:
            return False
        if self._last_daily_reschedule_date == today:
            return False
        self._last_daily_reschedule_date = today
        return True

    def _set_wifi_devices(self, wifi_devices: list[WifiDeviceConfig]) -> None:
        with self._wifi_devices_lock:
            self._wifi_devices = list(wifi_devices)

    def _get_wifi_devices_snapshot(self) -> list[WifiDeviceConfig]:
        with self._wifi_devices_lock:
            return list(self._wifi_devices)

    def _build_allowed_windows(self, assignments: list[DeviceAssignment]) -> list[tuple[int, int]]:
        windows: list[tuple[int, int]] = []
        for assignment in assignments:
            windows.append((assignment.allow_start_hour, assignment.allow_end_hour))
        return windows

    def _all_tasks_disallowed_now(self) -> bool:
        if not self._allowed_windows:
            return False
        current_hour = datetime.now().hour
        for start_hour, end_hour in self._allowed_windows:
            if self._is_hour_allowed(current_hour, start_hour, end_hour):
                return False
        return True

    @staticmethod
    def _is_hour_allowed(current_hour: int, start_hour: int, end_hour: int) -> bool:
        if start_hour < end_hour:
            return start_hour <= current_hour < end_hour
        if start_hour > end_hour:
            return current_hour >= start_hour or current_hour < end_hour
        return True
