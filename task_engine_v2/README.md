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
- `configs/devices.json`：仅 WiFi 设备列表。
- `configs/task_list.json`：任务分配与统一时间窗口。
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
python task_engine_v2/run.py --devices task_engine_v2/configs/devices.json --task-list task_engine_v2/configs/task_list.json --log-level INFO
```

可选参数：

- `--daily-reschedule-hour`：每天触发一次“重新调度”的小时（24 小时制，默认 `7`）。

## 5. 配置说明

### 5.1 devices（WiFi 设备）

`devices.json` 仅维护设备连接信息：

```json
{
  "wifi_devices": [
    { "serial": "192.168.0.130:42379" },
    { "serial": "192.168.0.131:37033" }
  ]
}
```

### 5.2 task_list（任务分配与统一时间窗口）

支持两种用法：

1. 指定设备运行指定任务：

```json
{
  "assignments": [
    {
      "device_id": "N0URB50103",
      "task_file": "tasks/ad_watch_kuaishou.json",
      "allow_start_hour": 7,
      "allow_end_hour": 24
    }
  ]
}
```

2. 不写 `device_id`：表示当前在线所有设备都运行该任务；并且运行中新增设备也会自动执行：

```json
{
  "assignments": [
    {
      "task_file": "tasks/ad_watch_kuaishou.json",
      "allow_start_hour": 7,
      "allow_end_hour": 24
    }
  ]
}
```

时间窗口说明：

- `allow_start_hour` 和 `allow_end_hour` 统一在 `task_list.json` 中控制。
- 任务文件中的执行时间窗口配置已废弃（保留仅用于兼容，不作为调度依据）。

### 5.3 任务文件结构

- `entry`：进入流程（启动应用 + steps）。
- `execute`：循环执行参数（截图周期、activity、scenarios 配置中的 `have_text` 匹配）。
- `exit`：退出条件（最长时长、动作触发）。

`execute` 关键字段补充：

- `poll_interval_seconds`：每轮循环的轮询间隔秒数，默认 `5`。
- `required_activities`：允许执行任务的 Activity 白名单。当前 Activity 不在此列表时，会先执行一次 `back`，然后进入下一轮。
- `screenshot_dir`：截图目录。
- `save_screenshots`：是否保留运行截图，默认 `false`。
  - `false`：截图仅用于 OCR/匹配，使用后自动删除。
  - `true`：保留运行截图，便于排查问题。
- `scenarios`：场景列表，按配置顺序依次匹配，命中第一个后立即执行其 `action`，本轮不再继续匹配后续 scenario。
- `activity_random_swipe_up`：可选。在指定 Activity 中按随机间隔执行上滑，适合“刷视频”类任务。
  - `enabled`：是否启用。
  - `activities`：限定在哪些 Activity 中触发；为空时表示所有 `required_activities` 命中的页面都可触发。
  - `interval_min_seconds` / `interval_max_seconds`：两次随机上滑的最小/最大间隔秒数。
  - `start_x` / `start_y` / `end_x` / `end_y`：滑动起止坐标。
  - `duration_ms`：滑动时长，单位毫秒。

### 5.4 execute.scenarios 配置说明

基本示例：

```json
{
  "execute": {
    "poll_interval_seconds": 3,
    "required_activities": [
      "com.example/.MainActivity"
    ],
    "scenarios": [
      {
        "name": "领取奖励",
        "have_text": ["恭喜获得", "领取奖励"],
        "scope": "center",
        "action": {
          "type": "click_text",
          "click_target": "领取奖励"
        }
      },
      {
        "name": "兜底关闭",
        "have_text": [],
        "scope": "top_right",
        "action": {
          "type": "tap",
          "x": 1180,
          "y": 180
        }
      }
    ]
  }
}
```

匹配规则：

- `scenarios` 按数组顺序依次判断，命中首个后立即执行，不会继续尝试后面的 scenario。
- 场景判断使用 `line` OCR 结果，适合做页面文案识别。
- `have_text` 中的文本关系是 **AND**：数组内所有文本都命中才算匹配。
- 文本匹配时会忽略空格，采用“包含”判断，不要求整行完全相等。
- `scope` 会先裁剪识别区域，再在该区域内判断 `have_text`。
- 当 `have_text` 为空数组，或未配置 `have_text` 时，该 scenario 会被视为“无条件命中”。通常应放在最后作为兜底，否则会抢先命中，导致后续 scenario 不再执行。

`scenario` 支持字段：

- `name`：可选。场景名称，仅用于日志输出，未填写时默认 `unnamed-scenario`。
- `have_text`：可选，字符串数组。用于描述命中该场景必须出现的文本。
- `scope`：可选，默认 `full`。表示该 scenario 的识别范围。
- `action`：必填。命中后的动作配置，支持的动作类型见下文。
- `stop_task`：可选，默认 `false`。为 `true` 时，当前 scenario 执行完后立即结束任务。

### 5.5 execute.scenarios.action 支持的参数说明

`scenario.action` 与 `entry.steps` 使用同一套动作执行器，支持的 `type` 如下：

- `click_text`
- `tap`
- `swipe`
- `back`
- `home`
- `sleep`
- `launch_app`
- `stop_task`

各动作参数：

- `click_text`
  - `type`：固定为 `click_text`。
  - `click_target`：必填。要点击的目标文本，可为字符串或字符串数组。
  - `target_match`：可选。仅当 `click_target` 为数组时生效；`and`（默认）表示全部命中，`or` 表示任意一个命中即可。
  - `scope`：可选，默认 `full`。点击目标文本时使用的 OCR 范围。
  - `offset`：可选。点击偏移量，格式 `{"x": 10, "y": -20}`。
  - `ocr_mode`：可选。支持 `line` / `word` / `hybrid`。不过在 `execute` 循环里，`click_text` 当前默认仍是“优先 `word`，失败回退 `line`”。
- `tap`
  - `type`：固定为 `tap`。
  - `x` / `y`：必填。点击坐标。
    - 传整数时，表示基于 `1264x2780` 基准分辨率的绝对坐标，运行时会自动按设备分辨率缩放。
    - 传 `0.0 ~ 1.0` 之间的小数时，表示按屏幕宽高的百分比点击。例如：`"x": 0.5, "y": 0.6` 表示点击屏幕宽度 50%、高度 60% 的位置。
  - `offset`：可选。点击偏移量。
- `swipe`
  - `type`：固定为 `swipe`。
  - `start_x` / `start_y`：必填。起点坐标。
  - `end_x` / `end_y`：必填。终点坐标。
  - `duration_ms`：可选，默认 `300`。
- `sleep`
  - `type`：固定为 `sleep`。
  - `seconds`：可选，默认 `1`。
- `launch_app`
  - `type`：固定为 `launch_app`。
  - `package`：必填。应用包名。
  - `activity`：可选。启动 Activity。
- `back` / `home` / `stop_task`
  - 仅需 `type` 字段，无额外参数。

坐标相关说明：

- `tap`、`swipe`、`offset` 中的坐标，均按 `1264x2780` 基准分辨率编写。
- 引擎运行时会根据当前设备实际分辨率自动等比例缩放。
- 仅 `tap.x` / `tap.y` 支持百分比写法；当值为 `0.0 ~ 1.0` 的小数时，会按当前屏幕尺寸直接换算，不再走基准分辨率缩放。

### 5.6 entry.steps 与 action 字段说明

通用字段：

- `type`：动作类型。
- `click_target`：动作目标文本。可为字符串或字符串数组。
  - 字符串示例：`"click_target": "福利"`
  - 数组示例：`"click_target": ["福利", "任务"]`
- `target_match`：可选。仅当 `click_target` 为数组时生效。
  - `"and"`（默认）：数组内文本都要命中。
  - `"or"`：数组内任意一个命中即可。
- `offset`：可选。点击偏移量，格式为 `{"x": 10, "y": -20}`。该坐标值基于 `1264x2780` 的基准分辨率测量，引擎会在运行时自动根据当前设备的屏幕物理尺寸进行等比例自适应缩放。
  - 正数表示在原坐标基础上增加。
  - 负数表示在原坐标基础上减少。
  - 当前对 `tap` 和 `click_text` 生效。
  - `tap` 本身若使用百分比坐标，`offset` 仍然按基准分辨率缩放后再叠加。
- `scope`：识别范围（见下方 scope 定义）。
- `ocr_mode`：OCR 粒度（`line` 或 `word`）。

校验相关字段（针对 entry.steps）：

- `check_if_have`：可选。存在时表示该 step 执行后需要做 OCR 校验。
  - 可为字符串：`"check_if_have": "任务中心"`
  - 可为数组：`"check_if_have": ["任务中心", "看广告得金币"]`
- `check_scope`：可选。校验使用的范围；不填则回退到 `scope`。
- `check_wait_seconds`：可选。执行动作后，校验前等待秒数；默认 `1.0`。

### 5.7 scope 定义

基于当前截图实际宽高计算：

- `top`：上 20%
- `top_left`：上 20% 且左 50%
- `top_right`：上 20% 且右 50%
- `center`：中间 60%
- `center_left`：中间 60% 且左 50%
- `center_right`：中间 60% 且右 50%
- `bottom`：下 20%
- `bottom_left`：下 20% 且左 50%
- `bottom_right`：下 20% 且右 50%
- `full`：全屏

### 5.8 OCR 模式说明

- `line`：行级框，识别覆盖更完整，适合场景判断。
- `word`：词级框，点击定位更精准。

当前默认执行策略：

- 场景判断：优先 `line`。
- 点击动作 `click_text`：优先 `word`，失败后自动回退 `line`。

## 6. 执行流程

### 6.0 调度触发机制

- 初次启动：对当前在线设备执行一次任务链。
- 每日触发：到达 `daily_reschedule_hour` 后，调度器会进入新一轮 generation；在线设备在当前任务链结束后会被重新触发一次。
- 配置变更触发：`devices.json`、`task_list.json` 或其引用的任务文件发生变化后，调度器会自动进入新 generation；在线设备会按新配置重新触发。

说明：

- 运行中的任务链不会被强制中断；会在该轮结束后按新 generation 重新调度。
- 该机制为后续接入服务端配置更新预留了统一触发入口（generation advance）。

### 6.1 任务启动

1. 检查并自动点亮屏幕（若熄屏）。
2. 执行 `entry`。
3. `entry` 中每个 step 最多重试 5 次，失败则任务退出。

### 6.2 entry step 执行顺序

1. 截图。
2. 若配置了 `scope`，先按 scope 裁剪，再 OCR（坐标会映射回全图）。
3. 执行动作（`click_text` 会优先 word，再回退 line）。
4. 若配置了 `check_if_have`：等待 `check_wait_seconds` 后截图并 OCR 校验。
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
