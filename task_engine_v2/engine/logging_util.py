import logging
import os
import re
import sys

_ANSI_RESET = "\033[0m"
_ANSI_BOLD = "\033[1m"
_ANSI_GREEN = "\033[32m"
_ANSI_RED = "\033[31m"

_DEVICE_PREFIX = "task-chain-"


def _enable_windows_ansi() -> bool:
    if os.name != "nt":
        return True
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = ctypes.c_uint()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)) == 0:
            return False
        if kernel32.SetConsoleMode(handle, mode.value | 0x0004) == 0:  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
            return False
        return True
    except Exception:
        return False


class CompactFormatter(logging.Formatter):
    def __init__(self) -> None:
        super().__init__(datefmt="%m-%d %H:%M:%S")
        self._color_enabled = sys.stdout.isatty() and _enable_windows_ansi()

    @staticmethod
    def _is_state_log(msg: str) -> bool:
        lower = msg.lower()
        markers = (
            "task chain start item",
            "task chain finished item",
            "task start",
            "entry launch_app",
            "entry step done",
            "scenario matched",
            "task exit",
        )
        return any(marker in lower for marker in markers)

    @staticmethod
    def _is_failure_state(msg: str, level_name: str) -> bool:
        if level_name in ("ERROR", "CRITICAL"):
            return True
        lower = msg.lower()
        fail_markers = (
            "ok=false",
            "failed",
            "exception",
            "mismatch",
            "stopped because",
            "not found",
        )
        return any(marker in lower for marker in fail_markers)

    def _color_line(self, line: str, msg: str, level_name: str) -> str:
        if not self._color_enabled:
            return line
        if not self._is_state_log(msg):
            return line
        color = _ANSI_RED if self._is_failure_state(msg, level_name) else _ANSI_GREEN
        return f"{_ANSI_BOLD}{color}{line}{_ANSI_RESET}"

    def format(self, record: logging.LogRecord) -> str:
        thread_name = record.threadName or ""
        if thread_name.startswith(_DEVICE_PREFIX):
            device = thread_name[len(_DEVICE_PREFIX):]
        else:
            device = thread_name

        created_time = self.formatTime(record, self.datefmt)
        msg = record.getMessage()

        # Remove redundant "| device=<id>" from message when device is already shown
        if device:
            msg = re.sub(r"\s*\|\s*device=" + re.escape(device), "", msg)

        if record.exc_info and not record.exc_text:
            record.exc_text = self.formatException(record.exc_info)
        if record.exc_text:
            msg = msg + "\n" + record.exc_text
        if record.stack_info:
            msg = msg + "\n" + self.formatStack(record.stack_info)

        scenario_value = getattr(record, "scenario", "")
        if scenario_value:
            line = f"{created_time} | {record.levelname} | {device} | {scenario_value} | {msg}"
        else:
            line = f"{created_time} | {record.levelname} | {device} | {msg}"
        return self._color_line(line, msg, record.levelname)


def setup_logging(level: str = "INFO") -> None:
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    handler = logging.StreamHandler()
    handler.setFormatter(CompactFormatter())
    root_logger.addHandler(handler)
