from __future__ import annotations

from pathlib import Path
import logging
import time

from .adb_client import ADBClient
from .ocr_engine import OCREngine, OCRBox, filter_by_scope


logger = logging.getLogger(__name__)


class ActionExecutor:
    def __init__(self, adb: ADBClient, ocr: OCREngine, screenshot_dir: str) -> None:
        self.adb = adb
        self.ocr = ocr
        self.screenshot_dir = Path(screenshot_dir)
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)

    def execute(
        self,
        action: dict,
        ocr_boxes: list[OCRBox] | None = None,
        screen_size: tuple[int, int] | None = None,
        apply_scope_filter: bool = True,
    ) -> bool:
        action_type = str(action.get("type", "")).strip()
        if not action_type:
            logger.error("empty action type")
            return False

        if action_type == "sleep":
            seconds = max(0.1, float(action.get("seconds", 1)))
            time.sleep(seconds)
            return True

        if action_type == "back":
            return self.adb.press_back()

        if action_type == "home":
            return self.adb.press_home()

        if action_type == "tap":
            x = int(action.get("x", 0))
            y = int(action.get("y", 0))
            logger.info("tap action coords | x=%s | y=%s", x, y)
            return self.adb.tap(x, y)

        if action_type == "swipe":
            return self.adb.swipe(
                int(action.get("start_x", 0)),
                int(action.get("start_y", 0)),
                int(action.get("end_x", 0)),
                int(action.get("end_y", 0)),
                int(action.get("duration_ms", 300)),
            )

        if action_type == "launch_app":
            package = str(action.get("package", "")).strip()
            activity = str(action.get("activity", "")).strip() or None
            if not package:
                logger.error("launch_app missing package")
                return False
            return self.adb.launch_app(package=package, activity=activity)

        if action_type == "stop_task":
            # Stop is handled by TaskRunner exit logic.
            return True

        if action_type == "click_text":
            target = str(action.get("target", "")).strip()
            scope = str(action.get("scope", "full"))
            ocr_mode = str(action.get("ocr_mode", "word")).strip().lower()
            if not target:
                logger.error("click_text missing target")
                return False
            candidates: list[tuple[str, list[OCRBox]]] = []
            if ocr_boxes is not None:
                candidates.append((ocr_mode, ocr_boxes))
            else:
                if ocr_mode in ("word", "hybrid"):
                    candidates.append(("word", self._capture_and_ocr_words()))
                    candidates.append(("line", self._capture_and_ocr()))
                else:
                    candidates.append(("line", self._capture_and_ocr()))

            width = screen_size[0] if screen_size else None
            height = screen_size[1] if screen_size else None

            for idx, (mode_name, boxes) in enumerate(candidates, start=1):
                if not boxes:
                    continue
                scoped = boxes
                if apply_scope_filter:
                    scoped = filter_by_scope(boxes, scope, width=width, height=height)
                box = self._find_box_by_text(scoped, target)
                if box is None:
                    if idx < len(candidates):
                        logger.info(
                            "click_text fallback next OCR mode | current=%s | target=%s | scope=%s",
                            mode_name,
                            target,
                            scope,
                        )
                    continue

                x, y, est_left, est_width = self._estimate_target_center(box, target)
                logger.info(
                    "click_text tap coords | ocr_mode=%s | scope=%s | target=%s | x=%s | y=%s | box=(%s,%s,%s,%s) | est=(left=%s,width=%s)",
                    mode_name,
                    scope,
                    target,
                    x,
                    y,
                    box.left,
                    box.top,
                    box.width,
                    box.height,
                    est_left,
                    est_width,
                )
                return self.adb.tap(x, y)

            logger.warning("click_text target not found: scope=%s target=%s", scope, target)
            return False

        logger.error("unsupported action type: %s", action_type)
        return False

    def _capture_and_ocr(self) -> list[OCRBox]:
        temp_img = self.screenshot_dir / "_tmp_action_ocr.png"
        if not self.adb.capture_screenshot(temp_img):
            return []
        return self.ocr.extract_text_boxes(temp_img)

    def _capture_and_ocr_words(self) -> list[OCRBox]:
        temp_img = self.screenshot_dir / "_tmp_action_ocr_words.png"
        if not self.adb.capture_screenshot(temp_img):
            return []
        return self.ocr.extract_word_boxes(temp_img)

    @staticmethod
    def _find_box_by_text(boxes: list[OCRBox], target: str) -> OCRBox | None:
        normalized_target = target.replace(" ", "")
        for box in boxes:
            if normalized_target in box.text.replace(" ", ""):
                return box
        return None

    @staticmethod
    def _estimate_target_center(box: OCRBox, target: str) -> tuple[int, int, int, int]:
        normalized_text = box.text.replace(" ", "")
        normalized_target = target.replace(" ", "")

        if not normalized_text or not normalized_target:
            x, y = box.center
            return x, y, box.left, box.width

        start_idx = normalized_text.find(normalized_target)
        if start_idx < 0:
            x, y = box.center
            return x, y, box.left, box.width

        total_chars = len(normalized_text)
        target_chars = len(normalized_target)
        char_width = box.width / max(total_chars, 1)

        est_left = int(round(box.left + start_idx * char_width))
        est_width = max(1, int(round(target_chars * char_width)))
        x = est_left + est_width // 2
        y = box.top + box.height // 2
        return x, y, est_left, est_width
