from __future__ import annotations

from pathlib import Path
import os
import logging
import time
from typing import Any

from .adb_client import ADBClient
from .ocr_engine import OCREngine, OCRBox, filter_by_scope


logger = logging.getLogger(__name__)


class ActionExecutor:
    def __init__(self, adb: ADBClient, ocr: OCREngine, screenshot_dir: str, save_screenshots: bool = False) -> None:
        self.adb = adb
        self.ocr = ocr
        self.screenshot_dir = Path(screenshot_dir)
        self.save_screenshots = save_screenshots
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
            offset_x, offset_y = self._parse_offset(action.get("offset"))
            final_x = x + offset_x
            final_y = y + offset_y
            logger.info(
                "tap action coords | x=%s | y=%s | offset=(%s,%s) | final=(%s,%s)",
                x,
                y,
                offset_x,
                offset_y,
                final_x,
                final_y,
            )
            return self.adb.tap(final_x, final_y)

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
            targets = self._normalize_targets(action.get("target", ""))
            match_mode = self._normalize_match_mode(action.get("target_match", "and"))
            offset_x, offset_y = self._parse_offset(action.get("offset"))
            scope = str(action.get("scope", "full"))
            ocr_mode = str(action.get("ocr_mode", "word")).strip().lower()
            if not targets:
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
                click_target, box = self._find_click_target(scoped, targets, match_mode)
                if click_target is None or box is None:
                    if idx < len(candidates):
                        logger.info(
                            "click_text fallback next OCR mode | current=%s | targets=%s | match=%s | scope=%s",
                            mode_name,
                            targets,
                            match_mode,
                            scope,
                        )
                    continue

                x, y, est_left, est_width = self._estimate_target_center(box, click_target)
                final_x = x + offset_x
                final_y = y + offset_y
                logger.info(
                    "click_text tap coords | ocr_mode=%s | scope=%s | target=%s | targets=%s | match=%s | x=%s | y=%s | offset=(%s,%s) | final=(%s,%s) | box=(%s,%s,%s,%s) | est=(left=%s,width=%s)",
                    mode_name,
                    scope,
                    click_target,
                    targets,
                    match_mode,
                    x,
                    y,
                    offset_x,
                    offset_y,
                    final_x,
                    final_y,
                    box.left,
                    box.top,
                    box.width,
                    box.height,
                    est_left,
                    est_width,
                )
                return self.adb.tap(final_x, final_y)

            logger.warning("click_text target not found: scope=%s targets=%s match=%s", scope, targets, match_mode)
            return False

        logger.error("unsupported action type: %s", action_type)
        return False

    def _capture_and_ocr(self) -> list[OCRBox]:
        temp_img = self.screenshot_dir / "_tmp_action_ocr.png"
        if not self.adb.capture_screenshot(temp_img):
            return []
        try:
            return self.ocr.extract_text_boxes(temp_img)
        finally:
            if not self.save_screenshots:
                self._safe_unlink(temp_img)

    def _capture_and_ocr_words(self) -> list[OCRBox]:
        temp_img = self.screenshot_dir / "_tmp_action_ocr_words.png"
        if not self.adb.capture_screenshot(temp_img):
            return []
        try:
            return self.ocr.extract_word_boxes(temp_img)
        finally:
            if not self.save_screenshots:
                self._safe_unlink(temp_img)

    @staticmethod
    def _safe_unlink(path: Path) -> None:
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        except Exception:
            logger.debug("skip deleting temp screenshot: %s", path, exc_info=True)

    @staticmethod
    def _find_box_by_text(boxes: list[OCRBox], target: str) -> OCRBox | None:
        normalized_target = target.replace(" ", "")
        for box in boxes:
            if normalized_target in box.text.replace(" ", ""):
                return box
        return None

    def _find_click_target(
        self,
        boxes: list[OCRBox],
        targets: list[str],
        match_mode: str,
    ) -> tuple[str | None, OCRBox | None]:
        if match_mode == "or":
            for target in targets:
                box = self._find_box_by_text(boxes, target)
                if box is not None:
                    return target, box
            return None, None

        matched_boxes: dict[str, OCRBox] = {}
        for target in targets:
            box = self._find_box_by_text(boxes, target)
            if box is None:
                return None, None
            matched_boxes[target] = box

        first_target = targets[0]
        return first_target, matched_boxes[first_target]

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

    @staticmethod
    def _parse_offset(raw_offset: Any) -> tuple[int, int]:
        if not isinstance(raw_offset, dict):
            return 0, 0
        try:
            offset_x = int(raw_offset.get("x", 0))
            offset_y = int(raw_offset.get("y", 0))
        except Exception:
            return 0, 0
        return offset_x, offset_y

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
