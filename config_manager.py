import json
import os
from typing import Dict, Any

# 公共的配置字典对象
CONFIG: Dict[str, Any] = {}

def load_config(config_path: str = "config.json") -> bool:
    """加载配置文件并更新到全局 CONFIG 变量中。"""
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            loaded_config = json.load(f)
            CONFIG.clear()
            CONFIG.update(loaded_config)
            
        # 确保截图目录存在并写入配置
        if 'settings' in CONFIG:
            screenshot_dir = CONFIG['settings'].get('screenshot_dir', 'temp_screenshots')
            if not os.path.exists(screenshot_dir):
                os.makedirs(screenshot_dir)
            CONFIG['settings']['screenshot_dir'] = screenshot_dir
        return True
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"无法加载或解析 {config_path}: {e}")
        return False


# 配置 demo
    {
      "name": "Music App Ad - Swipe Up",
      "screen_text": "汽水xxx音乐",
      "action": {
        "type": "swipe",
        "start_x": 500,
        "start_y": 1500,
        "end_x": 500,
        "end_y": 500,
        "duration_ms": 200
      }
    },