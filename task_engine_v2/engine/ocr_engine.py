from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
import logging
import platform


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class OCRBox:
    text: str
    left: int
    top: int
    width: int
    height: int

    @property
    def center(self) -> tuple[int, int]:
        return (self.left + self.width // 2, self.top + self.height // 2)


class OCREngine:
    def __init__(self) -> None:
        self._available = None
        self._lang = "zh-Hans-CN"

    def _check_available(self) -> bool:
        if self._available is not None:
            return self._available
        try:
            if not platform.system().lower().startswith("win"):
                logger.error("WinRT OCR only supports Windows")
                self._available = False
                return self._available

            from winrt.windows.globalization import Language
            from winrt.windows.media.ocr import OcrEngine

            lang = Language(self._lang)
            if not OcrEngine.is_language_supported(lang):
                logger.error("Windows OCR language not supported: %s", self._lang)
                self._available = False
                return self._available

            self._available = True
        except Exception as exc:
            logger.error("WinRT OCR unavailable: %s", exc)
            self._available = False
        return self._available

    def extract_text_boxes(self, image_path: str | Path) -> list[OCRBox]:
        if not self._check_available():
            logger.error("OCR unavailable. Please install WinRT packages and Windows OCR language pack.")
            return []

        abs_path = str(Path(image_path).resolve())
        try:
            return asyncio.run(self._extract_text_boxes_async(abs_path))
        except RuntimeError:
            # Fallback for environments with an active event loop.
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(self._extract_text_boxes_async(abs_path))
            finally:
                loop.close()
        except Exception as exc:
            logger.error("WinRT OCR failed: %s", exc)
            return []

    def extract_word_boxes(self, image_path: str | Path) -> list[OCRBox]:
        if not self._check_available():
            logger.error("OCR unavailable. Please install WinRT packages and Windows OCR language pack.")
            return []

        abs_path = str(Path(image_path).resolve())
        try:
            return asyncio.run(self._extract_word_boxes_async(abs_path))
        except RuntimeError:
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(self._extract_word_boxes_async(abs_path))
            finally:
                loop.close()
        except Exception as exc:
            logger.error("WinRT OCR word-level failed: %s", exc)
            return []

    async def _extract_text_boxes_async(self, abs_image_path: str) -> list[OCRBox]:
        from winrt.windows.globalization import Language
        from winrt.windows.graphics.imaging import BitmapDecoder
        from winrt.windows.media.ocr import OcrEngine
        from winrt.windows.storage import FileAccessMode, StorageFile

        file = await StorageFile.get_file_from_path_async(abs_image_path)
        stream = await file.open_async(FileAccessMode.READ)
        decoder = await BitmapDecoder.create_async(stream)
        software_bitmap = await decoder.get_software_bitmap_async()

        lang = Language(self._lang)
        engine = OcrEngine.try_create_from_language(lang)
        if not engine:
            logger.error("Failed to create WinRT OcrEngine with language %s", self._lang)
            return []

        result = await engine.recognize_async(software_bitmap)
        boxes: list[OCRBox] = []

        for line in result.lines:
            if not line.words:
                continue

            min_x = int(min(w.bounding_rect.x for w in line.words))
            min_y = int(min(w.bounding_rect.y for w in line.words))
            max_right = int(max(w.bounding_rect.x + w.bounding_rect.width for w in line.words))
            max_bottom = int(max(w.bounding_rect.y + w.bounding_rect.height for w in line.words))
            text = (line.text or "").strip()
            if not text:
                continue

            boxes.append(
                OCRBox(
                    text=text,
                    left=min_x,
                    top=min_y,
                    width=max_right - min_x,
                    height=max_bottom - min_y,
                )
            )

        return boxes

    async def _extract_word_boxes_async(self, abs_image_path: str) -> list[OCRBox]:
        from winrt.windows.globalization import Language
        from winrt.windows.graphics.imaging import BitmapDecoder
        from winrt.windows.media.ocr import OcrEngine
        from winrt.windows.storage import FileAccessMode, StorageFile

        file = await StorageFile.get_file_from_path_async(abs_image_path)
        stream = await file.open_async(FileAccessMode.READ)
        decoder = await BitmapDecoder.create_async(stream)
        software_bitmap = await decoder.get_software_bitmap_async()

        lang = Language(self._lang)
        engine = OcrEngine.try_create_from_language(lang)
        if not engine:
            logger.error("Failed to create WinRT OcrEngine with language %s", self._lang)
            return []

        result = await engine.recognize_async(software_bitmap)
        boxes: list[OCRBox] = []

        for line in result.lines:
            for word in line.words:
                text = (word.text or "").strip()
                if not text:
                    continue
                rect = word.bounding_rect
                boxes.append(
                    OCRBox(
                        text=text,
                        left=int(rect.x),
                        top=int(rect.y),
                        width=int(rect.width),
                        height=int(rect.height),
                    )
                )

        return boxes


def filter_by_scope(boxes: Iterable[OCRBox], scope: str, width: int | None = None, height: int | None = None) -> list[OCRBox]:
    box_list = list(boxes)
    if scope == "full":
        return box_list

    # Prefer dynamic bounds from current OCR result to avoid hard-coded resolution mismatch.
    if width is None:
        width = max((b.left + b.width for b in box_list), default=1080)
    if height is None:
        height = max((b.top + b.height for b in box_list), default=2400)

    # Keep minimum sane bounds for sparse OCR scenes.
    width = max(width, 200)
    height = max(height, 400)

    top_max_y = height * 0.2
    bottom_min_y = height * 0.8
    center_min_y = height * 0.2
    center_max_y = height * 0.8
    left_max_x = width * 0.5
    right_min_x = width * 0.5

    out: list[OCRBox] = []
    for box in box_list:
        cx, cy = box.center
        if scope == "center":
            if center_min_y <= cy <= center_max_y:
                out.append(box)
        elif scope == "top_left":
            if cx <= left_max_x and cy <= top_max_y:
                out.append(box)
        elif scope == "top_right":
            if cx >= right_min_x and cy <= top_max_y:
                out.append(box)
        elif scope == "top":
            if cy <= top_max_y:
                out.append(box)
        elif scope == "bottom":
            if cy >= bottom_min_y:
                out.append(box)
        elif scope == "bottom_left":
            if cx <= left_max_x and cy >= bottom_min_y:
                out.append(box)
        elif scope == "bottom_right":
            if cx >= right_min_x and cy >= bottom_min_y:
                out.append(box)
        else:
            out.append(box)
    return out
