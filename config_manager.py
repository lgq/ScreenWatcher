from typing import Any, Dict

from screenwatcher.config_service import ConfigError, ConfigService


CONFIG: Dict[str, Any] = {}


def load_config(config_path: str = "config.json", settings_path: str = "settings_config.json") -> bool:
    """兼容旧接口：加载配置文件并更新全局 CONFIG。"""
    config_service = ConfigService(base_config_path=config_path, settings_path=settings_path)
    try:
        loaded_config, _ = config_service.load_runtime_config()
    except ConfigError as exc:
        print(f"无法加载或解析配置文件: {exc}")
        return False

    CONFIG.clear()
    CONFIG.update(loaded_config)
    return True