
import subprocess
import os
import re
import time
from typing import Dict, List, Optional


def _extract_host(serial_or_host: str) -> str:
    value = str(serial_or_host).strip()
    if not value:
        return ""
    if ":" in value:
        return value.split(":", 1)[0].strip()
    return value


def _discover_wifi_serial_by_host(adb_path: str, host: str) -> str:
    """
    通过 `adb mdns services` 尝试发现指定 host 当前可用的无线调试端口。

    :param adb_path: adb 可执行文件路径。
    :param host: 设备 IP 或主机名。
    :return: 发现到的 serial（host:port），未发现返回空字符串。
    """
    if not host:
        return ""

    try:
        output = subprocess.check_output(
            [adb_path, "mdns", "services"],
            universal_newlines=True,
            encoding="utf-8",
            errors="ignore",
            timeout=3,
        )
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return ""

    host_lower = host.lower()
    for line in output.splitlines():
        if host_lower not in line.lower():
            continue
        match = re.search(r"([a-zA-Z0-9._-]+):(\d+)", line)
        if match:
            discovered_host = match.group(1)
            discovered_port = match.group(2)
            # mDNS 输出中 host 大小写可能变化，这里采用大小写不敏感匹配。
            if discovered_host.lower() == host_lower:
                return f"{discovered_host}:{discovered_port}"
    return ""


def _run_adb_command(adb_path: str, args: List[str], timeout: int = 5) -> str:
    try:
        return subprocess.check_output(
            [adb_path, *args],
            universal_newlines=True,
            encoding="utf-8",
            errors="ignore",
            timeout=timeout,
        )
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return ""


def _disconnect_wifi_target(adb_path: str, target: str) -> None:
    if not target:
        return
    _run_adb_command(adb_path, ["disconnect", target], timeout=4)


def _refresh_wifi_serial(adb_path: str, serial: str, retries: int = 3, interval_seconds: float = 0.6) -> str:
    host = _extract_host(serial)
    if not host:
        return ""

    for attempt in range(retries):
        discovered_serial = _discover_wifi_serial_by_host(adb_path, host)
        if discovered_serial:
            return discovered_serial
        if attempt < retries - 1:
            time.sleep(interval_seconds)
    return ""


def _connect_wifi_with_recovery(adb_path: str, serial: str) -> Optional[str]:
    if connect_wifi_device(adb_path, serial):
        return serial

    # 端口漂移时先清理旧连接，避免 adb 保留失效 endpoint 影响重连。
    _disconnect_wifi_target(adb_path, serial)
    host = _extract_host(serial)
    _disconnect_wifi_target(adb_path, host)

    discovered_serial = _refresh_wifi_serial(adb_path, serial)
    if not discovered_serial:
        return None

    if discovered_serial != serial:
        print(f"ADB Wi-Fi 发现端口变化: {serial} -> {discovered_serial}")
    _disconnect_wifi_target(adb_path, discovered_serial)

    if connect_wifi_device(adb_path, discovered_serial):
        return discovered_serial

    # 端口刚切换后可能存在短暂窗口，等待后再次发现并重试一次。
    latest_serial = _refresh_wifi_serial(adb_path, serial, retries=2, interval_seconds=1.0)
    if latest_serial and latest_serial != discovered_serial:
        print(f"ADB Wi-Fi 再次发现端口变化: {discovered_serial} -> {latest_serial}")
        _disconnect_wifi_target(adb_path, latest_serial)
        if connect_wifi_device(adb_path, latest_serial):
            return latest_serial

    return None


def _extract_activity_component(dumpsys_output: str) -> str:
    """
    从 dumpsys 输出中提取前台 activity 组件名，格式为 package/activity。

    :param dumpsys_output: dumpsys 命令输出文本。
    :return: 组件名（例如 "com.android.settings/.Settings"），未找到则返回空字符串。
    """
    # 常见格式示例：
    # mResumedActivity: ActivityRecord{... u0 com.xxx/.MainActivity t123}
    # topResumedActivity=ActivityRecord{... com.xxx/com.xxx.MainActivity}
    match = re.search(r'([a-zA-Z0-9_\.]+/[a-zA-Z0-9_\.$]+)', dumpsys_output)
    return match.group(1) if match else ""

def get_connected_devices(adb_path: str) -> List[str]:
    """
    获取通过 ADB 连接的所有设备的序列号。

    :param adb_path: adb 可执行文件的路径。
    :return: 一个包含所有设备序列号的列表。
    """
    try:
        result = subprocess.check_output([adb_path, "devices"], universal_newlines=True)
        devices = []
        for line in result.strip().split('\n')[1:]: # Skip the first line "List of devices attached"
            if "device" in line:
                serial = line.split('\t')[0]
                devices.append(serial)
        return devices
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"执行 adb devices 失败: {e}")
        return []


def connect_wifi_device(adb_path: str, serial: str) -> bool:
    """
    连接一个通过 Wi-Fi 调试的 ADB 设备。

    :param adb_path: adb 可执行文件的路径。
    :param serial: 设备地址，格式为 host:port。
    :return: 成功或已连接返回 True，否则返回 False。
    """
    try:
        result = subprocess.check_output(
            [adb_path, "connect", serial],
            universal_newlines=True,
            encoding="utf-8",
            errors="ignore",
            timeout=5,
        )
        normalized = result.lower()
        if "connected to" in normalized or "already connected to" in normalized:
            print(f"ADB Wi-Fi 连接成功: {serial}")
            return True
        print(f"ADB Wi-Fi 连接结果异常: {serial}: {result.strip()}")
        return False
    except subprocess.TimeoutExpired:
        print(f"ADB Wi-Fi 连接超时: {serial}")
        return False
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"ADB Wi-Fi 连接失败 {serial}: {e}")
        return False


def connect_wifi_device_with_recovery(adb_path: str, serial: str) -> str:
    """
    连接 Wi-Fi 设备并在端口变化时自动恢复。返回最终可用 serial，失败返回空字符串。
    """
    resolved_serial = _connect_wifi_with_recovery(adb_path, serial)
    return resolved_serial or ""


def ensure_wifi_devices_connected(adb_path: str, wifi_devices: List[Dict[str, object]]) -> None:
    """
    尝试连接配置中的 Wi-Fi 调试设备。

    :param adb_path: adb 可执行文件的路径。
    :param wifi_devices: 设备配置列表，每项至少包含 serial。
    """
    connected_devices = set(get_connected_devices(adb_path))

    for item in wifi_devices:
        serial = str(item.get("serial", "")).strip()
        auto_connect = bool(item.get("auto_connect", True))
        if not serial or not auto_connect:
            continue

        if serial in connected_devices:
            continue

        resolved_serial = connect_wifi_device_with_recovery(adb_path, serial)
        if resolved_serial:
            connected_devices.add(resolved_serial)

def get_devices(adb_path: str) -> List[str]:
    """
    获取通过 ADB 连接的所有设备的序列号（别名）。

    :param adb_path: adb 可执行文件的路径。
    :return: 一个包含所有设备序列号的列表。
    """
    return get_connected_devices(adb_path)

def get_foreground_app(adb_path: str, device_serial: str) -> str:
    """
    获取指定设备当前前台运行的应用包名。

    :param adb_path: adb 可执行文件的路径。
    :param device_serial: 目标设备的序列号。
    :return: 当前前台应用的包名（例如 "com.tencent.mm"），获取失败则返回空字符串。
    """
    try:
        result = subprocess.check_output(
            [adb_path, "-s", device_serial, "shell", "dumpsys", "window"],
            universal_newlines=True, encoding='utf-8', errors='ignore'
        )
        for line in result.splitlines():
            if "mCurrentFocus" in line:
                if "null" in line:
                    continue  # 遇到多屏中某个屏幕焦点为空时，跳过并继续寻找下一个屏幕
                # 使用正则精确提取包名（匹配最后一个空格和 / 之间的合法应用包名）
                match = re.search(r'\s([a-zA-Z0-9_\.]+)/', line)
                if match:
                    return match.group(1)
                        
        # 如果 dumpsys window 没找到，使用备用方案查询 activity
        result_activity = subprocess.check_output(
            [adb_path, "-s", device_serial, "shell", "dumpsys", "activity", "activities"],
            universal_newlines=True, encoding='utf-8', errors='ignore'
        )
        for line in result_activity.splitlines():
            if "mResumedActivity" in line or "ResumedActivity" in line:
                match = re.search(r'\s([a-zA-Z0-9_\.]+)/', line)
                if match:
                    return match.group(1)
                        
        return ""
    except Exception as e:
        print(f"设备 {device_serial} 获取前台应用失败: {e}")
        return ""


def get_current_activity(adb_path: str, device_serial: str) -> str:
    """
    获取指定设备当前前台 activity（package/activity）。

    :param adb_path: adb 可执行文件的路径。
    :param device_serial: 目标设备的序列号。
    :return: 当前前台 activity（例如 "com.android.settings/.Settings"），获取失败则返回空字符串。
    """
    try:
        # 优先使用 activity dumpsys，稳定性通常优于 window dumpsys。
        result_activity = subprocess.check_output(
            [adb_path, "-s", device_serial, "shell", "dumpsys", "activity", "activities"],
            universal_newlines=True, encoding='utf-8', errors='ignore'
        )

        for line in result_activity.splitlines():
            if "mResumedActivity" in line or "ResumedActivity" in line or "topResumedActivity" in line:
                component = _extract_activity_component(line)
                if component:
                    return component

        # 兜底：从 window 当前焦点中提取 activity 组件。
        result_window = subprocess.check_output(
            [adb_path, "-s", device_serial, "shell", "dumpsys", "window"],
            universal_newlines=True, encoding='utf-8', errors='ignore'
        )

        for line in result_window.splitlines():
            if "mCurrentFocus" in line and "null" not in line:
                component = _extract_activity_component(line)
                if component:
                    return component

        return ""
    except Exception as e:
        print(f"设备 {device_serial} 获取当前 Activity 失败: {e}")
        return ""


def get_device_battery_info(adb_path: str, device_serial: str) -> Dict[str, object]:
    """
    获取设备电池信息。
    """
    info: Dict[str, object] = {
        "level": -1,
        "scale": 100,
        "charging": False,
        "status": "unknown",
    }
    try:
        result = subprocess.check_output(
            [adb_path, "-s", device_serial, "shell", "dumpsys", "battery"],
            universal_newlines=True,
            encoding="utf-8",
            errors="ignore",
        )
    except Exception as exc:
        print(f"设备 {device_serial} 获取电池信息失败: {exc}")
        return info

    status_map = {
        "1": "unknown",
        "2": "charging",
        "3": "discharging",
        "4": "not_charging",
        "5": "full",
    }

    for line in result.splitlines():
        if ":" not in line:
            continue
        key, raw_value = [part.strip() for part in line.split(":", 1)]
        if key == "level":
            try:
                info["level"] = int(raw_value)
            except ValueError:
                pass
        elif key == "scale":
            try:
                info["scale"] = int(raw_value)
            except ValueError:
                pass
        elif key == "status":
            info["status"] = status_map.get(raw_value, raw_value)
        # 一些设备 status 不稳定，但会正确标记供电来源，因此这里额外兜底 charging。
        elif key in {"AC powered", "USB powered", "Wireless powered", "Dock powered"} and raw_value.lower() == "true":
            info["charging"] = True

    if info["status"] in {"charging", "full"}:
        info["charging"] = True
    return info


def is_device_screen_on(adb_path: str, device_serial: str) -> bool:
    """
    获取设备屏幕是否点亮。
    """
    try:
        result = subprocess.check_output(
            [adb_path, "-s", device_serial, "shell", "dumpsys", "power"],
            universal_newlines=True,
            encoding="utf-8",
            errors="ignore",
        )
    except Exception as exc:
        print(f"设备 {device_serial} 获取屏幕状态失败: {exc}")
        return False

    lowered = result.lower()
    # 不同 Android 版本的 dumpsys power 字段并不一致，因此使用多种特征联合判断。
    if "display power: state=on" in lowered:
        return True
    if "mholdingdisplaysuspendblocker=true" in lowered:
        return True
    if "mwakefulness=awake" in lowered:
        return True
    return False

def take_screenshot(adb_path: str, device_serial: str, local_path: str) -> bool:
    """
    使用 ADB 从指定设备截屏并保存到本地。

    :param adb_path: adb 可执行文件的路径。
    :param device_serial: 目标设备的序列号。
    :param local_path: 截图保存到本地的路径。
    :return: 如果成功则返回 True，否则返回 False。
    """
    try:
        # 在设备上截屏
        device_path = "/sdcard/screenshot.png"
        try:
            # 先尝试带 -d 0 参数截屏以消除多屏幕警告（屏蔽错误输出）
            subprocess.check_call([adb_path, "-s", device_serial, "shell", "screencap", "-d", "0", device_path], stderr=subprocess.DEVNULL)
        except subprocess.CalledProcessError:
            # 若该设备不支持此参数，回退到默认的截屏命令
            subprocess.check_call([adb_path, "-s", device_serial, "shell", "screencap", device_path])
        # 将截图文件拉取到本地（静默执行，避免 adb pull 进度日志污染控制台）
        subprocess.check_call(
            [adb_path, "-s", device_serial, "pull", device_path, local_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        # 删除设备上的临时截图文件
        subprocess.check_call([adb_path, "-s", device_serial, "shell", "rm", device_path])
        # print(f"设备 {device_serial} 截图已保存至: {local_path}")
        return True
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"设备 {device_serial} 截图失败: {e}")
        return False

def click(adb_path: str, device_serial: str, x: int, y: int):
    """
    在指定设备的特定坐标处执行点击操作。

    :param adb_path: adb 可执行文件的路径。
    :param device_serial: 目标设备的序列号。
    :param x: 点击位置的 x 坐标。
    :param y: 点击位置的 y 坐标。
    """
    try:
        print(f"在设备 {device_serial} 上点击坐标: ({x}, {y})")
        subprocess.check_call([adb_path, "-s", device_serial, "shell", "input", "tap", str(x), str(y)])
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"在设备 {device_serial} 上点击失败: {e}")

def swipe(adb_path: str, device_serial: str, start_x: int, start_y: int, end_x: int, end_y: int, duration_ms: int):
    """
    在指定设备上执行滑动操作。

    :param adb_path: adb 可执行文件的路径。
    :param device_serial: 目标设备的序列号。
    :param start_x: 滑动起点的 x 坐标。
    :param start_y: 滑动起点的 y 坐标。
    :param end_x: 滑动终点的 x 坐标。
    :param end_y: 滑动终点的 y 坐标。
    :param duration_ms: 滑动持续时间（毫秒）。
    """
    try:
        print(f"在设备 {device_serial} 上滑动: 从 ({start_x}, {start_y}) 到 ({end_x}, {end_y})")
        subprocess.check_call([
            adb_path, "-s", device_serial, "shell", "input", "swipe",
            str(start_x), str(start_y), str(end_x), str(end_y), str(duration_ms)
        ])
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"在设备 {device_serial} 上滑动失败: {e}")

def launch_app(adb_path: str, device_serial: str, package_name: str):
    """
    在指定设备上启动一个应用程序。

    :param adb_path: adb 可执行文件的路径。
    :param device_serial: 目标设备的序列号。
    :param package_name: 要启动的应用的包名。
    """
    try:
        print(f"在设备 {device_serial} 上启动应用: {package_name}")
        # 先停止应用，再启动
        subprocess.check_call([
            adb_path, "-s", device_serial, "shell", "am", "force-stop", package_name
        ])
        subprocess.check_call([
            adb_path, "-s", device_serial, "shell", "monkey", "-p", package_name,
            "-c", "android.intent.category.LAUNCHER", "1"
        ])
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"在设备 {device_serial} 上启动应用 {package_name} 失败: {e}")

def back_home(adb_path: str, device_serial: str):
    """
    返回设备主屏幕。

    :param adb_path: adb 可执行文件的路径。
    :param device_serial: 目标设备的序列号。
    """
    try:
        print(f"在设备 {device_serial} 上返回主屏幕")
        subprocess.check_call([adb_path, "-s", device_serial, "shell", "input", "keyevent", "3"])
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"在设备 {device_serial} 上返回主屏幕失败: {e}")

def back(adb_path: str, device_serial: str):
    """
    模拟按下设备返回键（Back）。

    :param adb_path: adb 可执行文件的路径。
    :param device_serial: 目标设备的序列号。
    """
    try:
        print(f"在设备 {device_serial} 上按返回键")
        subprocess.check_call([adb_path, "-s", device_serial, "shell", "input", "keyevent", "4"])
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"在设备 {device_serial} 上按返回键失败: {e}")


if __name__ == '__main__':
    # --- 测试代码 ---
    # 请确保你的 adb 在系统路径中，或者在此处提供完整路径
    ADB_PATH = "adb"
    
    print("--- 正在获取连接的设备 ---")
    devices = get_connected_devices(ADB_PATH)
    if not devices:
        print("未检测到任何设备。")
    else:
        print(f"检测到设备: {devices}")
        # 选择第一个设备进行测试
        test_device = devices[0]

        # 测试获取当前 Activity
        print("\n--- 正在测试获取当前 Activity ---")
        current_activity = get_current_activity(ADB_PATH, test_device)
        if current_activity:
            print(f"设备 {test_device} 当前 Activity: {current_activity}")
        else:
            print(f"设备 {test_device} 未获取到当前 Activity")
        
        # 测试截图
        print("\n--- 正在测试截图 ---")
        if not os.path.exists("temp_screenshots"):
            os.makedirs("temp_screenshots")
        screenshot_path = os.path.join("temp_screenshots", f"{test_device}_test.png")
        take_screenshot(ADB_PATH, test_device, screenshot_path)
        
        # 测试点击 (请谨慎使用，这会在你的设备上执行真实点击)
        # print("\n--- 正在测试点击 (5秒后在 500, 1500 点击) ---")
        # import time
        # time.sleep(5)
        # click(ADB_PATH, test_device, 500, 1500)
        
        # 测试滑动 (请谨慎使用)
        # print("\n--- 正在测试滑动 (5秒后) ---")
        # time.sleep(5)
        # swipe(ADB_PATH, test_device, 500, 1500, 500, 500, 300)

        # 测试启动应用 (请将'com.android.settings'替换为你想启动的应用包名)
        # print("\n--- 正在测试启动系统设置 (5秒后) ---")
        # time.sleep(5)
        # launch_app(ADB_PATH, test_device, "com.android.settings")

    print("\n--- adb_util.py 测试完成 ---")
