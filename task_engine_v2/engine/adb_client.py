from __future__ import annotations

from pathlib import Path
import subprocess
import logging
import re


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
