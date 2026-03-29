
import asyncio

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
