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
    # 安装包运行时直接使用安装目录下的配置与运行数据。
    if getattr(sys, "frozen", False):
        return get_app_root()

    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return os.path.join(local_app_data, APP_NAME)
    return os.path.join(get_app_root(), ".runtime")


def get_defaults_root() -> str:
    app_root = get_app_root()

    candidates = [
        os.path.join(app_root, "defaults"),
        os.path.join(app_root, "_internal", "defaults"),
    ]

    meipass = getattr(sys, "_MEIPASS", "")
    if meipass:
        candidates.append(os.path.join(meipass, "defaults"))

    # 兼容开发态目录、PyInstaller onedir 和运行时临时解包目录三种布局。
    for path in candidates:
        if os.path.isdir(path):
            return path

    return app_root


def ensure_directory(path: str) -> str:
    os.makedirs(path, exist_ok=True)
    return path


def ensure_runtime_layout() -> str:
    data_root = ensure_directory(get_user_data_dir())
    ensure_directory(os.path.join(data_root, "app_configs"))
    ensure_directory(os.path.join(data_root, "temp_screenshots"))
    ensure_directory(os.path.join(data_root, "wifi_test_screenshots"))
    # 远控配置下发前先准备好备份目录，方便后续按 revision 留存快照。
    ensure_directory(os.path.join(data_root, "backups"))
    return data_root


def get_runtime_file_path(file_name: str) -> str:
    return os.path.join(ensure_runtime_layout(), file_name)


def get_runtime_backup_dir() -> str:
    return ensure_directory(os.path.join(ensure_runtime_layout(), "backups"))


def get_default_files() -> List[str]:
    defaults_root = get_defaults_root()
    files = ["settings_config.json", "config.json"]
    if os.path.isdir(defaults_root):
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
        # 只在目标文件不存在时拷贝，避免默认模板覆盖用户已经调整过的本地配置。
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
                # app_configs 也遵循“只补缺失，不主动覆盖”的原则。
                if not os.path.exists(target):
                    shutil.copy2(source, target)

    # 兜底：若打包资源缺失，仍生成最小可运行 settings，避免启动即报“配置文件不存在”。
    settings_path = os.path.join(data_root, "settings_config.json")
    if not os.path.exists(settings_path):
        with open(settings_path, "w", encoding="utf-8") as f:
            f.write(
                '{\n'
                '  "adb_path": "adb",\n'
                '  "adb_wifi_devices": [],\n'
                '  "keep_scope_temp_images": false,\n'
                '  "poll_interval_seconds": 3,\n'
                '  "run_duration_minutes": 60,\n'
                '  "screenshot_dir": "temp_screenshots"\n'
                '}\n'
            )

    config_path = os.path.join(data_root, "config.json")
    if not os.path.exists(config_path):
        with open(config_path, "w", encoding="utf-8") as f:
            f.write('{\n  "scenarios": []\n}\n')

    return data_root


def get_bundled_adb_path() -> str:
    app_root = get_app_root()
    candidates = [
        os.path.join(app_root, "platform-tools", "adb.exe"),
        os.path.join(app_root, "_internal", "platform-tools", "adb.exe"),
    ]

    meipass = getattr(sys, "_MEIPASS", "")
    if meipass:
        candidates.append(os.path.join(meipass, "platform-tools", "adb.exe"))

    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate

    return ""
