
import asyncio
import builtins
from datetime import datetime

_original_print = builtins.print


def _timestamped_print(*args, **kwargs):
    timestamp = datetime.now().strftime("%H:%M:%S")
    # 若首个参数以 \n 开头，保留换行在时间戳之前，避免时间戳被挤到行尾
    if args and isinstance(args[0], str) and args[0].startswith("\n"):
        _original_print(f"\n[{timestamp}]", args[0][1:], *args[1:], **kwargs)
    else:
        _original_print(f"[{timestamp}]", *args, **kwargs)


builtins.print = _timestamped_print

from screenwatcher.config_service import ConfigError, ConfigService
from screenwatcher.device_monitor import DeviceMonitor
from screenwatcher.device_processor import DeviceProcessor
from screenwatcher.remote_sync import RemoteControlService


async def main():
    config_service = ConfigService()
    try:
        config_service.load_settings()
    except ConfigError as exc:
        print(f"配置加载失败，程序退出。原因: {exc}")
        return

    remote_control_service = RemoteControlService(config_service)
    monitor = DeviceMonitor(config_service, DeviceProcessor(config_service), remote_control_service)
    await monitor.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[系统] 已收到中断信号，程序退出。")
