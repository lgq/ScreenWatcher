import logging


class ScenarioAwareFormatter(logging.Formatter):
    def __init__(self) -> None:
        super().__init__()
        self._default_formatter = logging.Formatter(
            "%(asctime)s | %(levelname)s | %(threadName)s | %(name)s | %(message)s"
        )
        self._scenario_formatter = logging.Formatter(
            "%(asctime)s | %(levelname)s | %(threadName)s | %(scenario)s | %(name)s | %(message)s"
        )

    def format(self, record: logging.LogRecord) -> str:
        scenario_value = getattr(record, "scenario", "")
        if scenario_value:
            return self._scenario_formatter.format(record)
        return self._default_formatter.format(record)


def setup_logging(level: str = "INFO") -> None:
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    handler = logging.StreamHandler()
    handler.setFormatter(ScenarioAwareFormatter())
    root_logger.addHandler(handler)
