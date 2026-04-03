from __future__ import annotations

from datetime import datetime
from pathlib import Path
import logging
import os
import random
import time
from typing import Any, Callable

from .adb_client import ADBClient
from .actions import ActionExecutor
from .matcher import find_first_matching_scenario
from .models import TaskConfig
from .ocr_engine import OCRBox, OCREngine


logger = logging.getLogger(__name__)


class TaskRunner:
    def __init__(
        self,
        device_id: str,
        task: TaskConfig,
        adb_path: str = "adb",
        should_stop: Callable[[], bool] | None = None,
    ) -> None:
        self.device_id = device_id
        self.task = task
        self.adb = ADBClient(device_id=device_id, adb_path=adb_path)
        self.ocr = OCREngine()
        self.action_executor = ActionExecutor(
            self.adb,
            self.ocr,
            screenshot_dir=task.execute.screenshot_dir,
            save_screenshots=task.execute.save_screenshots,
        )
        self._should_stop_callback = should_stop
        self._next_random_swipe_due: float | None = None

    def run(self) -> None:
        exit_reason = "completed"
        try:
            logger.info("task start | device=%s | task=%s", self.device_id, self.task.name)

            if self._should_stop_now():
                exit_reason = "scheduler_stop"
                logger.info("task exit by scheduler stop before start | device=%s | task=%s", self.device_id, self.task.name)
                return
            
            # Check if current time is within allowed hours
            if not self._is_within_allowed_hours():
                exit_reason = "not_in_allowed_hours"
                logger.warning(
                    "task exit because current time not in allowed range | device=%s | task=%s | allowed_hours=%s-%s",
                    self.device_id,
                    self.task.name,
                    self.task.execute.allow_start_hour,
                    self.task.execute.allow_end_hour,
                )
                return
            
            if not self.adb.is_device_connected():
                exit_reason = "device_disconnected"
                logger.warning("task exit because device disconnected | device=%s", self.device_id)
                return
            screen_ok = self.adb.ensure_screen_on()
            logger.info("task start ensure screen on | device=%s | ok=%s", self.device_id, screen_ok)
            if not self._run_entry():
                exit_reason = "entry_failed"
                logger.error("task exit because entry failed | device=%s | task=%s", self.device_id, self.task.name)
                return

            started = time.monotonic()
            screenshot_dir = Path(self.task.execute.screenshot_dir) / self.device_id.replace(":", "_")
            screenshot_dir.mkdir(parents=True, exist_ok=True)

            while True:
                if self._should_stop_now():
                    exit_reason = "scheduler_stop"
                    logger.info("task exit by scheduler stop | device=%s | task=%s", self.device_id, self.task.name)
                    return

                if not self.adb.is_device_connected():
                    exit_reason = "device_disconnected"
                    logger.warning("task exit because device disconnected | device=%s", self.device_id)
                    return

                elapsed = int(time.monotonic() - started)
                if elapsed >= self.task.exit.max_duration_seconds:
                    exit_reason = "duration"
                    logger.info("task exit by duration | device=%s | task=%s", self.device_id, self.task.name)
                    return

                img_name = datetime.now().strftime("%Y%m%d_%H%M%S_%f") + ".png"
                img_path = screenshot_dir / img_name

                if not self.adb.capture_screenshot(img_path):
                    logger.error("screenshot failed | device=%s | task=%s", self.device_id, self.task.name)
                    self._sleep_poll()
                    continue
                try:
                    current_activity = self.adb.current_activity()
                    required = self.task.execute.required_activities
                    if required and current_activity not in required:
                        logger.error(
                            "activity mismatch | device=%s | current=%s | expected=%s",
                            self.device_id,
                            current_activity,
                            required,
                        )
                        back_ok = self.adb.press_back()
                        logger.info("activity mismatch back | device=%s | ok=%s", self.device_id, back_ok)
                        self._sleep_poll()
                        continue

                    self._try_activity_random_swipe_up(current_activity)

                    # Scenario matching keeps line-level OCR for better recall.
                    boxes = self.ocr.extract_text_boxes(img_path)
                    screen_size = self._get_image_size(img_path)
                    scenario = find_first_matching_scenario(self.task.execute.scenarios, boxes, screen_size=screen_size)

                    if scenario is None:
                        logger.info("no scenario matched | device=%s", self.device_id)
                        self._sleep_poll()
                        continue

                    action_type = str(scenario.action.get("type", ""))
                    if action_type == "click_text":
                        # Click prefers word-level boxes, then falls back to line-level boxes.
                        word_boxes = self.ocr.extract_word_boxes(img_path)
                        ok = self.action_executor.execute(scenario.action, ocr_boxes=word_boxes, screen_size=screen_size)
                        if not ok:
                            logger.info("scenario click_text fallback to line OCR | device=%s", self.device_id)
                            ok = self.action_executor.execute(scenario.action, ocr_boxes=boxes, screen_size=screen_size)
                    else:
                        ok = self.action_executor.execute(scenario.action, ocr_boxes=boxes, screen_size=screen_size)
                    logger.info(
                        "scenario matched | action=%s | ok=%s",
                        action_type,
                        ok,
                        extra={"scenario": f"scenario={scenario.name}"},
                    )

                    if scenario.stop_task or action_type in self.task.exit.stop_on_action_types:
                        exit_reason = "action"
                        logger.info("task exit by action | device=%s | action=%s", self.device_id, action_type)
                        return

                    self._sleep_poll()
                finally:
                    if not self.task.execute.save_screenshots:
                        self._safe_unlink(img_path)
        except Exception:
            exit_reason = "exception"
            logger.exception("task exit by exception | device=%s | task=%s", self.device_id, self.task.name)
            raise
        finally:
            self._exit_to_home(exit_reason)

    def _run_entry(self) -> bool:
        if self._should_stop_now():
            logger.info("entry stop by scheduler | device=%s", self.device_id)
            return False

        if self.task.entry.start_from_home:
            self.adb.press_home()
            time.sleep(1)

        launch = self.task.entry.launch
        if launch:
            ok = self.action_executor.execute(
                {
                    "type": "launch_app",
                    "package": launch.get("package", ""),
                    "activity": launch.get("activity", ""),
                }
            )
            logger.info("entry launch_app | device=%s | ok=%s", self.device_id, ok)
            if not ok:
                return False
            time.sleep(float(launch.get("wait_seconds", 3)))

        for idx, step in enumerate(self.task.entry.steps, start=1):
            ok = self._run_entry_step_with_retry(step=step, step_index=idx, max_retries=5)
            if not ok:
                logger.error(
                    "entry step failed after retries | device=%s | step=%s | type=%s",
                    self.device_id,
                    idx,
                    step.get("type", ""),
                )
                return False
        return True

    def _run_entry_step_with_retry(self, step: dict, step_index: int, max_retries: int) -> bool:
        step_type = str(step.get("type", ""))
        targets = self._normalize_targets(step.get("target", ""))
        target_match = self._normalize_match_mode(step.get("target_match", "and"))
        scope = str(step.get("scope", "full"))
        ocr_mode = str(step.get("ocr_mode", "line")).strip().lower()
        # logger.info(targets and f"entry step | device=%s | step=%s | type=%s | targets=%s" or f"entry step | device=%s | step=%s | type=%s", self.device_id, step_index, step_type, targets)

        for attempt in range(1, max_retries + 1):
            if self._should_stop_now():
                logger.info(
                    "entry step stopped by scheduler | device=%s | step=%s | attempt=%s/%s",
                    self.device_id,
                    step_index,
                    attempt,
                    max_retries,
                )
                return False

            if not self.adb.is_device_connected():
                logger.warning(
                    "entry step stopped because device disconnected | device=%s | step=%s | attempt=%s/%s",
                    self.device_id,
                    step_index,
                    attempt,
                    max_retries,
                )
                return False

            before_boxes, screen_size = self._capture_ocr_for_entry(
                step_index=step_index,
                attempt=attempt,
                phase="before",
                scope=scope,
                ocr_mode=ocr_mode,
            )
            if before_boxes is None:
                logger.warning(
                    "entry step screenshot/ocr failed | device=%s | step=%s | attempt=%s/%s",
                    self.device_id,
                    step_index,
                    attempt,
                    max_retries,
                )
                time.sleep(1)
                continue

            if step_type == "click_text" and not self._targets_satisfied(before_boxes, targets, target_match):
                logger.warning(
                    "entry step target not found | device=%s | step=%s | scope=%s | targets=%s | match=%s | attempt=%s/%s",
                    self.device_id,
                    step_index,
                    scope,
                    targets,
                    target_match,
                    attempt,
                    max_retries,
                )
                time.sleep(1)
                continue

            if step_type == "click_text":
                word_boxes, _ = self._capture_ocr_for_entry(
                    step_index=step_index,
                    attempt=attempt,
                    phase="before_word",
                    scope=scope,
                    ocr_mode="word",
                )
                ok = self.action_executor.execute(
                    step,
                    ocr_boxes=word_boxes or [],
                    screen_size=screen_size,
                    apply_scope_filter=False,
                )
                if not ok:
                    logger.info(
                        "entry step click_text fallback to line OCR | device=%s | step=%s | attempt=%s/%s",
                        self.device_id,
                        step_index,
                        attempt,
                        max_retries,
                    )
                    ok = self.action_executor.execute(
                        step,
                        ocr_boxes=before_boxes,
                        screen_size=screen_size,
                        apply_scope_filter=False,
                    )
            else:
                ok = self.action_executor.execute(
                    step,
                    ocr_boxes=before_boxes,
                    screen_size=screen_size,
                    apply_scope_filter=False,
                )
            if not ok:
                logger.warning(
                    "entry step action failed | device=%s | step=%s | type=%s | attempt=%s/%s",
                    self.device_id,
                    step_index,
                    step_type,
                    attempt,
                    max_retries,
                )
                time.sleep(1)
                continue

            if self._is_entry_step_completed(step=step, step_index=step_index, attempt=attempt):
                logger.info(
                    "entry step done | device=%s | step=%s | type=%s | attempt=%s/%s",
                    self.device_id,
                    step_index,
                    step_type,
                    attempt,
                    max_retries,
                )
                return True

            logger.warning(
                "entry step completion check failed | device=%s | step=%s | type=%s | attempt=%s/%s",
                self.device_id,
                step_index,
                step_type,
                attempt,
                max_retries,
            )
            time.sleep(1)

        return False

    def _is_entry_step_completed(self, step: dict, step_index: int, attempt: int) -> bool:
        check = step.get("check")
        if not check:
            return True

        check_texts: list[str]
        if isinstance(check, str):
            check_texts = [check.strip()] if check.strip() else []
        elif isinstance(check, list):
            check_texts = [str(x).strip() for x in check if str(x).strip()]
        else:
            return False

        if not check_texts:
            return False

        scope = str(step.get("check_scope", step.get("scope", "full")))

        time.sleep(1)
        ocr_mode = str(step.get("ocr_mode", "line")).strip().lower()
        after_boxes, _ = self._capture_ocr_for_entry(
            step_index=step_index,
            attempt=attempt,
            phase="after",
            scope=scope,
            ocr_mode=ocr_mode,
        )
        if after_boxes is None:
            return False

        return all(self._contains_text(after_boxes, text) for text in check_texts)

    def _capture_ocr_for_entry(
        self,
        step_index: int,
        attempt: int,
        phase: str,
        scope: str = "full",
        ocr_mode: str = "line",
    ) -> tuple[list[OCRBox] | None, tuple[int, int] | None]:
        screenshot_dir = Path(self.task.execute.screenshot_dir) / self.device_id.replace(":", "_") / "entry"
        screenshot_dir.mkdir(parents=True, exist_ok=True)
        img_name = datetime.now().strftime("%Y%m%d_%H%M%S_%f") + f"_step{step_index}_{phase}_{attempt}.png"
        img_path = screenshot_dir / img_name
        crop_path: Path | None = None

        if not self.adb.capture_screenshot(img_path):
            return None, None
        try:
            screen_size = self._get_image_size(img_path)

            if scope == "full":
                return self._extract_boxes_with_mode(img_path, ocr_mode), screen_size

            # Scope-first strategy for entry: crop image first, then OCR.
            crop_path, offset = self._crop_image_by_scope(img_path=img_path, scope=scope)
            if crop_path is None:
                return self._extract_boxes_with_mode(img_path, ocr_mode), screen_size

            cropped_boxes = self._extract_boxes_with_mode(crop_path, ocr_mode)
            offset_x, offset_y = offset
            return [
                OCRBox(
                    text=box.text,
                    left=box.left + offset_x,
                    top=box.top + offset_y,
                    width=box.width,
                    height=box.height,
                )
                for box in cropped_boxes
            ], screen_size
        finally:
            if not self.task.execute.save_screenshots:
                if crop_path is not None:
                    self._safe_unlink(crop_path)
                self._safe_unlink(img_path)

    @staticmethod
    def _get_image_size(img_path: Path) -> tuple[int, int] | None:
        try:
            from PIL import Image

            with Image.open(img_path) as img:
                return img.size
        except Exception:
            return None

    def _extract_boxes_with_mode(self, img_path: Path, ocr_mode: str) -> list[OCRBox]:
        if ocr_mode == "word":
            return self.ocr.extract_word_boxes(img_path)
        return self.ocr.extract_text_boxes(img_path)

    def _crop_image_by_scope(self, img_path: Path, scope: str) -> tuple[Path | None, tuple[int, int]]:
        try:
            from PIL import Image
        except Exception:
            logger.warning("scope crop requires pillow, fallback to full-image OCR | device=%s", self.device_id)
            return None, (0, 0)

        with Image.open(img_path) as img:
            width, height = img.size
            x1, y1, x2, y2 = self._scope_bounds(scope=scope, width=width, height=height)
            if x2 <= x1 or y2 <= y1:
                return None, (0, 0)

            cropped = img.crop((x1, y1, x2, y2))
            crop_path = img_path.with_name(f"{img_path.stem}_crop_{scope}{img_path.suffix}")
            cropped.save(crop_path)
            return crop_path, (x1, y1)

    @staticmethod
    def _scope_bounds(scope: str, width: int, height: int) -> tuple[int, int, int, int]:
        top_max_y = int(height * 0.2)
        bottom_min_y = int(height * 0.8)
        center_min_y = int(height * 0.2)
        center_max_y = int(height * 0.8)
        left_max_x = int(width * 0.5)
        right_min_x = int(width * 0.5)

        if scope == "top":
            return (0, 0, width, top_max_y)
        if scope == "top_left":
            return (0, 0, left_max_x, top_max_y)
        if scope == "top_right":
            return (right_min_x, 0, width, top_max_y)
        if scope == "center":
            return (0, center_min_y, width, center_max_y)
        if scope == "center_left":
            return (0, center_min_y, left_max_x, center_max_y)
        if scope == "center_right":
            return (right_min_x, center_min_y, width, center_max_y)
        if scope == "bottom":
            return (0, bottom_min_y, width, height)
        if scope == "bottom_left":
            return (0, bottom_min_y, left_max_x, height)
        if scope == "bottom_right":
            return (right_min_x, bottom_min_y, width, height)
        return (0, 0, width, height)

    @staticmethod
    def _contains_text(boxes, target: str) -> bool:
        normalized_target = target.replace(" ", "")
        for box in boxes:
            if normalized_target in box.text.replace(" ", ""):
                return True
        return False

    def _targets_satisfied(self, boxes: list[OCRBox], targets: list[str], match_mode: str) -> bool:
        if not targets:
            return False
        if match_mode == "or":
            return any(self._contains_text(boxes, target) for target in targets)
        return all(self._contains_text(boxes, target) for target in targets)

    @staticmethod
    def _normalize_targets(raw_target: Any) -> list[str]:
        if isinstance(raw_target, str):
            target = raw_target.strip()
            return [target] if target else []
        if isinstance(raw_target, list):
            return [str(item).strip() for item in raw_target if str(item).strip()]
        target = str(raw_target).strip()
        return [target] if target else []

    @staticmethod
    def _normalize_match_mode(raw_mode: Any) -> str:
        mode = str(raw_mode).strip().lower()
        if mode == "or":
            return "or"
        return "and"

    def _sleep_poll(self) -> None:
        total = max(0.1, float(self.task.execute.poll_interval_seconds))
        slept = 0.0
        step = 0.2
        while slept < total:
            if self._should_stop_now():
                return
            chunk = min(step, total - slept)
            time.sleep(chunk)
            slept += chunk

    def _should_stop_now(self) -> bool:
        if self._should_stop_callback is None:
            return False
        try:
            return bool(self._should_stop_callback())
        except Exception:
            logger.debug("scheduler stop callback failed | device=%s", self.device_id, exc_info=True)
            return False

    def _try_activity_random_swipe_up(self, current_activity: str) -> None:
        cfg = self.task.execute.activity_random_swipe_up or {}
        if not cfg or not bool(cfg.get("enabled", False)):
            return

        activities = [str(x) for x in cfg.get("activities", [])]
        if activities and current_activity not in activities:
            return

        now = time.monotonic()
        if self._next_random_swipe_due is not None and now < self._next_random_swipe_due:
            return

        min_seconds = max(1, int(cfg.get("interval_min_seconds", 10)))
        max_seconds = max(min_seconds, int(cfg.get("interval_max_seconds", min_seconds)))

        start_x = int(cfg.get("start_x", 500))
        start_y = int(cfg.get("start_y", 800))
        end_x = int(cfg.get("end_x", 500))
        end_y = int(cfg.get("end_y", 400))
        duration_ms = int(cfg.get("duration_ms", 200))

        ok = self.adb.swipe(start_x, start_y, end_x, end_y, duration_ms)
        logger.info(
            "activity random swipe up | device=%s | current=%s | ok=%s | from=(%s,%s) | to=(%s,%s) | duration_ms=%s",
            self.device_id,
            current_activity,
            ok,
            start_x,
            start_y,
            end_x,
            end_y,
            duration_ms,
        )

        next_interval = random.randint(min_seconds, max_seconds)
        self._next_random_swipe_due = now + next_interval

    def _exit_to_home(self, reason: str) -> None:
        exit_activity = self.adb.current_activity()
        home_ok = self.adb.press_home()
        logger.info("task exit go home | device=%s | reason=%s | ok=%s", self.device_id, reason, home_ok)

        package = self._resolve_exit_package(exit_activity)
        if not package:
            logger.warning("task exit force-stop skipped | device=%s | reason=%s | no package", self.device_id, reason)
            return

        stop_ok = self.adb.force_stop_app(package)
        logger.info(
            "task exit force-stop | device=%s | reason=%s | package=%s | ok=%s",
            self.device_id,
            reason,
            package,
            stop_ok,
        )

    def _resolve_exit_package(self, exit_activity: str) -> str:
        if "/" in exit_activity:
            activity_package = exit_activity.split("/", 1)[0].strip()
            if activity_package and not self._is_launcher_package(activity_package):
                return activity_package

        launch = self.task.entry.launch or {}
        launch_package = str(launch.get("package", "")).strip()
        if launch_package and not self._is_launcher_package(launch_package):
            return launch_package

        return ""

    @staticmethod
    def _is_launcher_package(package: str) -> bool:
        p = package.lower()
        return (
            "launcher" in p
            or p in {
                "com.android.systemui",
                "com.google.android.apps.nexuslauncher",
            }
        )

    @staticmethod
    def _safe_unlink(path: Path) -> None:
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        except Exception:
            logger.debug("skip deleting runtime screenshot: %s", path, exc_info=True)

    def _is_within_allowed_hours(self) -> bool:
        """Check if current time is within the allowed execution hours."""
        current_hour = datetime.now().hour
        start_hour = self.task.execute.allow_start_hour
        end_hour = self.task.execute.allow_end_hour
        
        # Both are on the same day or wrapping midnight
        if start_hour < end_hour:
            # Normal case: e.g., 7-24 or 9-17
            return start_hour <= current_hour < end_hour
        elif start_hour > end_hour:
            # Wrapping midnight: e.g., 22-6 (10 PM to 6 AM)
            return current_hour >= start_hour or current_hour < end_hour
        else:
            # start_hour == end_hour, all day allowed
            return True
