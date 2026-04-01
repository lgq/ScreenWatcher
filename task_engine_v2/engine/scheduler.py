from __future__ import annotations

from pathlib import Path
import logging
import threading
import subprocess
import time

from .models import DeviceAssignment, WifiDeviceConfig, load_assignments, load_task_config, load_wifi_devices
from .adb_client import ADBClient
from .task_runner import TaskRunner


logger = logging.getLogger(__name__)


class DeviceTaskScheduler:
    def __init__(self, assignments_file: str, adb_path: str = "adb") -> None:
        self.assignments_file = assignments_file
        self.adb_path = adb_path
        self.poll_interval_seconds = 3
        self.wifi_poll_interval_seconds = 12
        # config_serial -> last successfully resolved serial (may differ after port drift)
        self._wifi_resolved: dict[str, str] = {}
        self._wifi_stop_event = threading.Event()

    def run(self) -> None:
        assignments = load_assignments(self.assignments_file)
        if not assignments:
            logger.warning("no valid assignments found in %s", self.assignments_file)
            return

        wifi_devices = load_wifi_devices(self.assignments_file)
        assignments_path = Path(self.assignments_file).resolve()
        if not wifi_devices:
            fallback_path = assignments_path.parent / "devices.json"
            if fallback_path != assignments_path and fallback_path.exists():
                wifi_devices = load_wifi_devices(fallback_path)
                if wifi_devices:
                    logger.info(
                        "wifi_devices not found in %s, fallback to %s | count=%s",
                        assignments_path.name,
                        fallback_path.name,
                        len(wifi_devices),
                    )
        if not wifi_devices:
            logger.warning(
                "no wifi devices configured in %s (supported keys: wifi_devices, adb_wifi_devices)",
                assignments_path.name,
            )

        running_threads: dict[str, threading.Thread] = {}
        handled_devices: set[str] = set()
        wifi_thread: threading.Thread | None = None

        if wifi_devices:
            logger.info("scheduler connecting wifi devices | count=%s", len(wifi_devices))
            wifi_thread = threading.Thread(
                target=self._wifi_connect_loop,
                args=(wifi_devices,),
                name="wifi-connect-loop",
                daemon=True,
            )
            wifi_thread.start()

        logger.info("scheduler started | watch hot-plug devices enabled")
        try:
            while True:
                # Reap finished threads.
                finished = [device for device, thread in running_threads.items() if not thread.is_alive()]
                for device in finished:
                    running_threads.pop(device, None)

                connected_devices = set(self._list_connected_devices())

                # A disconnected device should be eligible for a fresh schedule after reconnect.
                handled_devices.intersection_update(connected_devices)

                for device in connected_devices:
                    if device in running_threads or device in handled_devices:
                        continue

                    matched_assignments = self._resolve_assignments_for_device(
                        device_id=device,
                        assignments=assignments,
                    )
                    if not matched_assignments:
                        continue

                    mute_ok = ADBClient(device_id=device, adb_path=self.adb_path).ensure_muted()
                    logger.info("device connected, mute applied | device=%s | ok=%s", device, mute_ok)

                    thread = threading.Thread(
                        target=self._run_task_chain_for_device,
                        args=(device, matched_assignments, assignments_path),
                        name=f"task-chain-{device}",
                        daemon=False,
                    )
                    thread.start()

                    running_threads[device] = thread
                    handled_devices.add(device)
                    logger.info("task chain scheduled | device=%s | count=%s", device, len(matched_assignments))

                time.sleep(self.poll_interval_seconds)
        except KeyboardInterrupt:
            logger.info("scheduler interrupted, waiting running tasks to finish")
        finally:
            self._wifi_stop_event.set()
            if wifi_thread and wifi_thread.is_alive():
                wifi_thread.join(timeout=2)

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

    def _run_task_chain_for_device(self, device_id: str, assignments: list[DeviceAssignment], assignments_path: Path) -> None:
        if not assignments:
            return

        loop_assignments = [item for item in assignments if item.need_loop]

        for index, assignment in enumerate(assignments, start=1):
            if not self._is_device_connected(device_id):
                logger.warning("task chain stop because device disconnected | device=%s", device_id)
                return
            self._run_single_assignment(
                device_id=device_id,
                assignment=assignment,
                assignments_path=assignments_path,
                index=index,
                total=len(assignments),
            )

        if not loop_assignments:
            return

        logger.info("task chain entering loop mode | device=%s | loop_count=%s", device_id, len(loop_assignments))
        loop_index = 0
        while True:
            if not self._is_device_connected(device_id):
                logger.warning("task chain loop stopped because device disconnected | device=%s", device_id)
                return
            assignment = loop_assignments[loop_index]
            self._run_single_assignment(
                device_id=device_id,
                assignment=assignment,
                assignments_path=assignments_path,
                index=loop_index + 1,
                total=len(loop_assignments),
                loop_mode=True,
            )
            loop_index = (loop_index + 1) % len(loop_assignments)

    def _run_single_assignment(
        self,
        device_id: str,
        assignment: DeviceAssignment,
        assignments_path: Path,
        index: int,
        total: int,
        loop_mode: bool = False,
    ) -> None:
        task_file = Path(assignment.task_file)
        if not task_file.is_absolute():
            task_file = (assignments_path.parent / task_file).resolve()

        task = load_task_config(task_file)
        logger.info(
            "task chain start item | device=%s | index=%s/%s | loop_mode=%s | need_loop=%s | task=%s",
            device_id,
            index,
            total,
            loop_mode,
            assignment.need_loop,
            task.name,
        )

        runner = TaskRunner(device_id=device_id, task=task, adb_path=self.adb_path)
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

    def _wifi_connect_loop(self, wifi_devices: list[WifiDeviceConfig]) -> None:
        # Run one immediate attempt, then periodic retries in background.
        while not self._wifi_stop_event.is_set():
            try:
                self._connect_wifi_devices(wifi_devices)
            except Exception:
                logger.exception("wifi connect loop failed")
            if self._wifi_stop_event.wait(self.wifi_poll_interval_seconds):
                break
