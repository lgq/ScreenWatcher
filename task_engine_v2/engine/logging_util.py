import logging
import re

_DEVICE_PREFIX = "task-chain-"


class CompactFormatter(logging.Formatter):
    def __init__(self) -> None:
        super().__init__(datefmt="%m-%d %H:%M:%S")

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
            return f"{created_time} | {record.levelname} | {device} | {scenario_value} | {msg}"
        return f"{created_time} | {record.levelname} | {device} | {msg}"


def setup_logging(level: str = "INFO") -> None:
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    handler = logging.StreamHandler()
    handler.setFormatter(CompactFormatter())
    root_logger.addHandler(handler)
