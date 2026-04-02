from __future__ import annotations

from pathlib import Path
import subprocess
import logging
import re
import time


logger = logging.getLogger(__name__)


class ADBClient:
    def __init__(self, device_id: str, adb_path: str = "adb") -> None:
        self.device_id = device_id
        self.adb_path = adb_path

    def _run(self, args: list[str], timeout: int = 20) -> subprocess.CompletedProcess[str]:
        cmd = [self.adb_path, "-s", self.device_id, *args]
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="ignore")

    def _run_shell(self, shell_cmd: str, timeout: int = 20) -> subprocess.CompletedProcess[str]:
        return self._run(["shell", shell_cmd], timeout=timeout)

    def is_device_connected(self) -> bool:
        cmd = [self.adb_path, "-s", self.device_id, "get-state"]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=10,
                encoding="utf-8",
                errors="ignore",
            )
        except Exception:
            return False
        return result.returncode == 0 and (result.stdout or "").strip() == "device"

    # ------------------------------------------------------------------
    # WiFi device helpers (static, no device_id needed)
    # ------------------------------------------------------------------

    @staticmethod
    def wifi_connect(serial: str, adb_path: str = "adb") -> bool:
        """Run `adb connect <serial>` and return True on success."""
        try:
            result = subprocess.run(
                [adb_path, "connect", serial],
                capture_output=True,
                text=True,
                timeout=10,
                encoding="utf-8",
                errors="ignore",
            )
            normalized = (result.stdout or "").lower()
            return "connected to" in normalized or "already connected to" in normalized
        except Exception:
            return False

    @staticmethod
    def wifi_disconnect(serial: str, adb_path: str = "adb") -> None:
        """Run `adb disconnect <serial>`, ignore errors."""
        try:
            subprocess.run(
                [adb_path, "disconnect", serial],
                capture_output=True,
                timeout=5,
            )
        except Exception:
            pass

    @staticmethod
    def _wifi_discover_serial(host: str, adb_path: str = "adb") -> str:
        """Use `adb mdns services` to find host:port for the given host IP.

        Handles both output formats produced by different adb versions:
          - 'host:port'  (newer adb)
          - 'host  port' (tab/space separated, older adb)
        """
        if not host:
            return ""
        try:
            result = subprocess.run(
                [adb_path, "mdns", "services"],
                capture_output=True,
                text=True,
                timeout=5,
                encoding="utf-8",
                errors="ignore",
            )
        except Exception:
            return ""
        host_lower = host.lower()
        for line in (result.stdout or "").splitlines():
            if host_lower not in line.lower():
                continue
            # Format 1: host:port
            match = re.search(r"([a-zA-Z0-9._-]+):(\d+)", line)
            if match and match.group(1).lower() == host_lower:
                return f"{match.group(1)}:{match.group(2)}"
            # Format 2: ip<spaces/tabs>port  (IPv4 only)
            match = re.search(r"(\d{1,3}(?:\.\d{1,3}){3})\s+(\d+)", line)
            if match and match.group(1).lower() == host_lower:
                return f"{match.group(1)}:{match.group(2)}"
        return ""

    @classmethod
    def wifi_connect_with_recovery(cls, serial: str, adb_path: str = "adb") -> str:
        """
        连接 WiFi 设备，自动处理端口漂移。
        返回最终可用 serial，失败返回空字符串。
        """
        logger.debug("wifi connect | serial=%s", serial)
        if cls.wifi_connect(serial, adb_path):
            return serial

        host = serial.split(":", 1)[0] if ":" in serial else serial
        logger.debug("wifi direct connect failed, starting recovery | serial=%s | host=%s", serial, host)
        cls.wifi_disconnect(serial, adb_path)
        cls.wifi_disconnect(host, adb_path)

        # mDNS discovery with retries
        discovered = ""
        for attempt in range(1, 4):
            discovered = cls._wifi_discover_serial(host, adb_path)
            if discovered:
                break
            logger.debug("wifi mdns discovery attempt %s/3 found nothing | host=%s", attempt, host)
            time.sleep(0.6)

        if not discovered:
            logger.warning("wifi mdns discovery failed | host=%s | original=%s", host, serial)
            return ""

        if discovered != serial:
            logger.info("wifi port drift detected | original=%s | discovered=%s", serial, discovered)

        cls.wifi_disconnect(discovered, adb_path)
        if cls.wifi_connect(discovered, adb_path):
            return discovered

        logger.debug("wifi connect failed after discovery, waiting for port to stabilise | discovered=%s", discovered)
        # One more retry after a short wait (port may still be stabilising)
        time.sleep(1.0)
        latest = cls._wifi_discover_serial(host, adb_path)
        if latest and latest != discovered:
            logger.info("wifi port drift on second discovery | prev=%s | latest=%s", discovered, latest)
            cls.wifi_disconnect(latest, adb_path)
            if cls.wifi_connect(latest, adb_path):
                return latest

        logger.warning(
            "wifi connect recovery exhausted | host=%s | tried=%s | final_discovery=%s",
            host, discovered, latest or "none",
        )
        return ""

    def tap(self, x: int, y: int) -> bool:
        result = self._run(["shell", "input", "tap", str(x), str(y)])
        return result.returncode == 0

    def swipe(self, start_x: int, start_y: int, end_x: int, end_y: int, duration_ms: int = 300) -> bool:
        result = self._run(
            [
                "shell",
                "input",
                "swipe",
                str(start_x),
                str(start_y),
                str(end_x),
                str(end_y),
                str(duration_ms),
            ]
        )
        return result.returncode == 0

    def press_back(self) -> bool:
        return self._run(["shell", "input", "keyevent", "4"]).returncode == 0

    def press_home(self) -> bool:
        return self._run(["shell", "input", "keyevent", "3"]).returncode == 0

    def ensure_muted(self) -> bool:
        """Try to set common audio streams to volume 0 across Android variants."""
        commands = [
            # Android media CLI (newer Android)
            "media volume --stream 3 --set 0",
            "media volume --stream 2 --set 0",
            "media volume --stream 5 --set 0",
            # cmd media_session fallback (some ROMs)
            "cmd media_session volume --stream 3 --set 0",
            # settings fallback (best-effort)
            "settings put system volume_music 0",
            "settings put system volume_ring 0",
            "settings put system volume_notification 0",
        ]

        success = False
        for shell_cmd in commands:
            try:
                result = self._run_shell(shell_cmd, timeout=10)
            except Exception:
                continue
            if result.returncode == 0:
                success = True
        return success

    def ensure_min_brightness(self) -> bool:
        """Try to set screen brightness to minimum across Android variants."""
        commands = [
            # Force manual brightness mode first.
            "settings put system screen_brightness_mode 0",
            # Set minimum brightness in classic system settings range [0,255].
            "settings put system screen_brightness 1",
            # Some ROMs keep VR brightness separately.
            "settings put system screen_brightness_for_vr 1",
            # Newer Android command interface (best-effort).
            "cmd display set-brightness 0.01",
        ]

        success = False
        for shell_cmd in commands:
            try:
                result = self._run_shell(shell_cmd, timeout=10)
            except Exception:
                continue
            if result.returncode == 0:
                success = True
        return success

    def is_screen_on(self) -> bool | None:
        # Try multiple dumpsys sources for ROM compatibility.
        power_result = self._run(["shell", "dumpsys", "power"], timeout=20)
        power_out = (power_result.stdout or "") + "\n" + (power_result.stderr or "")

        if "Display Power: state=ON" in power_out:
            return True
        if "Display Power: state=OFF" in power_out:
            return False
        if "mHoldingDisplaySuspendBlocker=true" in power_out:
            return True
        if "mHoldingDisplaySuspendBlocker=false" in power_out:
            return False

        display_result = self._run(["shell", "dumpsys", "display"], timeout=20)
        display_out = (display_result.stdout or "") + "\n" + (display_result.stderr or "")
        if re.search(r"\bmScreenState=ON\b", display_out):
            return True
        if re.search(r"\bmScreenState=OFF\b", display_out):
            return False

        return None

    def wake_screen(self) -> bool:
        # KEYCODE_WAKEUP does not toggle; it only wakes when screen is off.
        return self._run(["shell", "input", "keyevent", "224"]).returncode == 0

    def ensure_screen_on(self) -> bool:
        state = self.is_screen_on()
        if state is True:
            return True

        wake_ok = self.wake_screen()
        if not wake_ok:
            return False

        # Give the device a short moment to update power state.
        check_after = self.is_screen_on()
        return check_after is not False

    def force_stop_app(self, package: str) -> bool:
        package = package.strip()
        if not package:
            return False
        result = self._run(["shell", "am", "force-stop", package])
        return result.returncode == 0

    def launch_app(self, package: str, activity: str | None = None) -> bool:
        target = f"{package}/{activity}" if activity else package
        result = self._run(["shell", "am", "start", "-n" if activity else "-a", target] if activity else ["shell", "monkey", "-p", package, "-c", "android.intent.category.LAUNCHER", "1"])
        return result.returncode == 0

    def current_activity(self) -> str:
        outputs: list[str] = []

        # Newer Android versions often expose resumed/top activity here.
        activity_result = self._run(["shell", "dumpsys", "activity", "activities"], timeout=25)
        outputs.append((activity_result.stdout or "") + "\n" + (activity_result.stderr or ""))

        # Some ROMs only expose focus info in window dumpsys.
        window_result = self._run(["shell", "dumpsys", "window", "windows"], timeout=25)
        outputs.append((window_result.stdout or "") + "\n" + (window_result.stderr or ""))

        for output in outputs:
            activity = self._extract_activity_from_output(output)
            if activity:
                return activity

        logger.warning("unable to parse current activity | device=%s", self.device_id)
        return ""

    @staticmethod
    def _extract_activity_from_output(output: str) -> str:
        patterns = [
            # Examples: mResumedActivity: ActivityRecord{... u0 com.xxx/.MainActivity ...}
            r"mResumedActivity:.*?\s([A-Za-z0-9_.$]+/[A-Za-z0-9_.$]+)",
            r"topResumedActivity=ActivityRecord\{.*?\s([A-Za-z0-9_.$]+/[A-Za-z0-9_.$]+)",
            r"ResumedActivity.*?\s([A-Za-z0-9_.$]+/[A-Za-z0-9_.$]+)",
            r"mCurrentFocus=Window\{[^}]+\s([A-Za-z0-9_.$]+/[A-Za-z0-9_.$]+)\}",
            r"mFocusedApp=AppWindowToken\{[^}]+\s([A-Za-z0-9_.$]+/[A-Za-z0-9_.$]+)\}",
        ]
        for pattern in patterns:
            matched = re.search(pattern, output)
            if matched:
                return matched.group(1)
        return ""

    def capture_screenshot(self, save_path: str | Path) -> bool:
        out_path = Path(save_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        cmd = [self.adb_path, "-s", self.device_id, "exec-out", "screencap", "-p"]
        try:
            with out_path.open("wb") as fp:
                result = subprocess.run(cmd, stdout=fp, stderr=subprocess.PIPE, timeout=30)
        except subprocess.TimeoutExpired:
            logger.error("screenshot timeout for device=%s", self.device_id)
            return False

        if result.returncode != 0:
            logger.error("screenshot failed for device=%s, stderr=%s", self.device_id, result.stderr.decode("utf-8", errors="ignore"))
            return False
        return True
