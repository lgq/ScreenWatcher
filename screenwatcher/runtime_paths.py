import os
import shutil
import sys
from typing import List


APP_NAME = "ScreenWatcher"


def get_app_root() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_user_data_dir() -> str:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return os.path.join(local_app_data, APP_NAME)
    return os.path.join(get_app_root(), ".runtime")


def get_defaults_root() -> str:
    app_root = get_app_root()
    packaged_defaults = os.path.join(app_root, "defaults")
    if os.path.isdir(packaged_defaults):
        return packaged_defaults
    return app_root


def ensure_directory(path: str) -> str:
    os.makedirs(path, exist_ok=True)
    return path


def ensure_runtime_layout() -> str:
    data_root = ensure_directory(get_user_data_dir())
    ensure_directory(os.path.join(data_root, "app_configs"))
    ensure_directory(os.path.join(data_root, "temp_screenshots"))
    ensure_directory(os.path.join(data_root, "wifi_test_screenshots"))
    return data_root


def get_default_files() -> List[str]:
    defaults_root = get_defaults_root()
    files = ["settings_config.json", "config.json"]
    for name in os.listdir(defaults_root):
        if name.endswith("_config.json") and name not in files:
            files.append(name)
    return files


def sync_default_runtime_files() -> str:
    data_root = ensure_runtime_layout()
    defaults_root = get_defaults_root()

    for name in get_default_files():
        source = os.path.join(defaults_root, name)
        target = os.path.join(data_root, name)
        if os.path.isfile(source) and not os.path.exists(target):
            shutil.copy2(source, target)

    source_app_configs = os.path.join(defaults_root, "app_configs")
    target_app_configs = os.path.join(data_root, "app_configs")
    if os.path.isdir(source_app_configs):
        for root, _, files in os.walk(source_app_configs):
            relative_root = os.path.relpath(root, source_app_configs)
            target_root = target_app_configs if relative_root == "." else os.path.join(target_app_configs, relative_root)
            ensure_directory(target_root)
            for file_name in files:
                source = os.path.join(root, file_name)
                target = os.path.join(target_root, file_name)
                if not os.path.exists(target):
                    shutil.copy2(source, target)

    return data_root


def get_bundled_adb_path() -> str:
    candidate = os.path.join(get_app_root(), "platform-tools", "adb.exe")
    if os.path.isfile(candidate):
        return candidate
    return ""
