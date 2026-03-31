# Task Engine v2 (Independent)

这是一个与现有代码完全独立的任务执行器，按任务配置文件驱动设备自动化。

## 1. 功能概览

- 进入任务：从桌面启动应用，执行多步骤 entry。
- 执行任务：按轮询周期截图、OCR、匹配 scenario、执行动作。
- Activity 守护：不在 `required_activities` 时自动执行 `back` 并进入下一轮。
- OCR：基于 WinRT（Windows.Media.Ocr），支持 line/word 两种粒度。
- 场景匹配：按配置顺序匹配，命中首个后执行动作并停止本轮后续匹配。
- 退出清理：任务退出时自动回桌面，并 force-stop 当前任务应用。
- 多设备：支持多设备并发；支持运行中插入新设备后自动调度。

## 2. 目录

- `run.py`：启动入口。
- `engine/`：执行引擎。
- `configs/devices.example.json`：设备与任务映射示例。
- `configs/tasks/*.json`：任务配置示例。

## 3. 环境准备

1. 安装依赖：

```bash
pip install -r task_engine_v2/requirements.txt
```

2. 确保系统为 Windows，且已安装 Windows OCR 对应语言包（默认 `zh-Hans-CN`）。
3. 保证 `adb` 可用，且设备在 `adb devices` 可见。

## 4. 运行方式

```bash
python task_engine_v2/run.py --assignments task_engine_v2/configs/devices.json --log-level INFO
```

## 5. 配置说明

### 5.1 assignments（设备映射）

支持两种用法：

1. 指定设备运行指定任务：

```json
{
  "assignments": [
    {
      "device_id": "N0URB50103",
      "task_file": "tasks/ad_watch_kuaishou.json"
    }
  ]
}
```

2. 不写 `device_id`：表示当前在线所有设备都运行该任务；并且运行中新增设备也会自动执行：

```json
{
  "assignments": [
    {
      "task_file": "tasks/ad_watch_kuaishou.json"
    }
  ]
}
```

### 5.2 任务文件结构

- `entry`：进入流程（启动应用 + steps）。
- `execute`：循环执行参数（截图周期、activity、scenarios）。
- `exit`：退出条件（最长时长、动作触发）。

### 5.3 entry.steps 新增字段

通用字段：

- `type`：动作类型。
- `scope`：识别范围（见下方 scope 定义）。
- `ocr_mode`：OCR 粒度（`line` 或 `word`）。

校验相关字段：

- `check`：可选。存在时表示该 step 执行后需要做 OCR 校验。
  - 可为字符串：`"check": "任务中心"`
  - 可为数组：`"check": ["任务中心", "看广告得金币"]`
- `check_scope`：可选。校验使用的范围；不填则回退到 `scope`。
- `check_wait_seconds`：可选。执行动作后，校验前等待秒数；默认 `1.0`。

### 5.4 scope 定义

基于当前截图实际宽高计算：

- `top`：上 20%
- `top_left`：上 20% 且左 50%
- `top_right`：上 20% 且右 50%
- `center`：中间 60%
- `bottom`：下 20%
- `bottom_left`：下 20% 且左 50%
- `bottom_right`：下 20% 且右 50%
- `full`：全屏

### 5.5 OCR 模式说明

- `line`：行级框，识别覆盖更完整，适合场景判断。
- `word`：词级框，点击定位更精准。

当前默认执行策略：

- 场景判断：优先 `line`。
- 点击动作 `click_text`：优先 `word`，失败后自动回退 `line`。

## 6. 执行流程

### 6.1 任务启动

1. 检查并自动点亮屏幕（若熄屏）。
2. 执行 `entry`。
3. `entry` 中每个 step 最多重试 5 次，失败则任务退出。

### 6.2 entry step 执行顺序

1. 截图。
2. 若配置了 `scope`，先按 scope 裁剪，再 OCR（坐标会映射回全图）。
3. 执行动作（`click_text` 会优先 word，再回退 line）。
4. 若配置了 `check`：等待 `check_wait_seconds` 后截图并 OCR 校验。
5. 校验通过进入下一 step；5 次失败退出任务。

### 6.3 execute 循环

1. 截图。
2. 检查 `required_activities`。
3. 若不在活动页：记录日志，执行 `back`，进入下一轮。
4. OCR + scenario 顺序匹配。
5. 命中后执行动作；`click_text` 优先 word、失败回退 line。
6. 未命中则记录日志并进入下一轮。

### 6.4 退出流程

触发退出条件（超时或动作触发）后：

1. 回到桌面。
2. force-stop 当前任务应用。

## 7. 支持动作

- `click_text`
- `tap`
- `swipe`
- `back`
- `home`
- `sleep`
- `launch_app`
- `stop_task`

## 8. 调试建议

- 使用 `--log-level INFO` 观察每轮行为。
- `click_text` 日志会输出点击坐标与命中框，便于排查偏移问题。
- 先单设备调通，再扩展多设备并发。
