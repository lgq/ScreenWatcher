from __future__ import annotations

from .models import ScenarioConfig
from .ocr_engine import OCRBox, filter_by_scope


def _contains_text(boxes: list[OCRBox], target: str) -> bool:
    target = target.replace(" ", "").strip()
    if not target:
        return False
    for box in boxes:
        if target in box.text.replace(" ", ""):
            return True
    return False


def find_first_matching_scenario(
    scenarios: list[ScenarioConfig],
    boxes: list[OCRBox],
    screen_size: tuple[int, int] | None = None,
) -> ScenarioConfig | None:
    width = screen_size[0] if screen_size else None
    height = screen_size[1] if screen_size else None
    for scenario in scenarios:
        scoped_boxes = filter_by_scope(boxes, scenario.scope, width=width, height=height)
        if all(_contains_text(scoped_boxes, txt) for txt in scenario.screen_text):
            return scenario
    return None
