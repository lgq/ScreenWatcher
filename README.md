# ScreenWatcher 配置手册

本文档基于当前代码实现整理，目标是让后续新增或修改配置时有统一参考。

## 1. 配置文件结构与加载顺序

项目使用两层配置：

1. 全局设置文件：settings_config.json
2. 运行规则文件：
   - 默认：config.json
   - 应用专属：<包名>_config.json，例如 com.kuaishou.nebula_config.json

运行时逻辑：

1. 先读取 settings_config.json
2. 再通过 adb 获取当前前台应用包名
3. 若存在对应的 <包名>_config.json，则优先使用它
4. 否则回退到 config.json

说明：

- settings_config.json 始终会合并进最终运行配置（作为 settings 字段）
- 运行规则建议放在 config.json 或应用专属配置中

## 2. settings_config.json 字段

### 2.1 顶层字段

- adb_path
  - 类型：string
  - 默认值：adb
  - 作用：adb 可执行命令或路径

- keep_scope_temp_images
  - 类型：bool
  - 默认值：false
  - 作用：scope OCR 时是否保留临时裁剪图

- poll_interval_seconds
  - 类型：int
  - 默认值：3
  - 最小值：1
  - 作用：每台设备每轮处理间隔秒数

- run_duration_minutes
  - 类型：int
  - 默认值：30
  - 最小值：1
  - 作用：app_loop 模式下每个应用图标的持续监控分钟数

- screenshot_dir
  - 类型：string
  - 默认值：temp_screenshots
  - 作用：截图保存目录，不存在会自动创建

- adb_wifi_devices
  - 类型：array
  - 默认值：[]
  - 作用：配置需要自动 `adb connect` 的无线调试设备列表

- app_loop
  - 类型：array
  - 默认值：[]
  - 作用：为指定设备启用“应用轮询监控”

### 2.2 adb_wifi_devices 元素结构

支持两种写法：

1. 简写字符串

- `"192.168.1.23:5555"`

2. 对象写法

- serial
  - 类型：string
  - 可选
  - 默认值：由 `host:port` 组合而成

- host
  - 类型：string
  - 可选

- port
  - 类型：int
  - 可选
  - 默认值：5555

- auto_connect
  - 类型：bool
  - 可选
  - 默认值：true

说明：

- 程序在设备枚举前会自动执行 `adb connect`
- USB 设备和 Wi-Fi 设备可以同时存在
- 设备 serial 一般为 `IP:端口`，例如 `192.168.1.23:5555`

### 2.3 app_loop 元素结构

每个元素结构：

- device.id
  - 类型：string
  - 必填
  - 作用：设备序列号（adb devices 显示的 ID）

- device.name
  - 类型：string
  - 可选
  - 默认值：device.id
  - 作用：日志展示名称

- device.test_icon_position_list
  - 类型：array
  - 可选
  - 默认值：[]
  - 作用：应用图标坐标列表，轮询点击启动应用

坐标元素：

- x：int，必填
- y：int，必填

说明：

- 若某设备不在 app_loop 中，则走“简单监控模式”（不做应用切换）
- app_loop 中除上述字段外的其他字段会被忽略

## 3. 运行规则配置（config.json / <包名>_config.json）

### 3.1 支持的顶层字段

- _comment
  - 类型：string
  - 可选
  - 作用：备注说明，不参与逻辑

- back_activities
  - 类型：array[string]
  - 可选
  - 默认值：[]
  - 作用：当当前 Activity 命中时，执行返回键并结束本轮处理

- activity_random_swipe_up
  - 类型：object 或 false
  - 可选
  - 默认值：{}
  - 作用：当当前 Activity 命中时，随机延时后执行上滑，并跳过本轮 OCR 监控

- scenarios
  - 类型：array
  - 默认值：[]
  - 作用：OCR 场景识别与动作执行规则

## 4. activity_random_swipe_up 字段说明

### 4.1 字段列表

- enabled
  - 类型：bool
  - 默认值：true
  - 作用：是否启用该功能

- activities
  - 类型：string 或 array[string]
  - 默认值：[]
  - 作用：命中 Activity 的关键字列表（包含匹配）

- interval_min_seconds
  - 类型：int
  - 默认值：10
  - 最小值：1

- interval_max_seconds
  - 类型：int
  - 默认值：15
  - 规则：不得小于 interval_min_seconds

- start_x
  - 类型：int
  - 默认值：500

- start_y
  - 类型：int
  - 默认值：900

- end_x
  - 类型：int
  - 默认值：500

- end_y
  - 类型：int
  - 默认值：660

- x_variance
  - 类型：int
  - 默认值：20
  - 最小值：0
  - 作用：起终点 x 方向随机抖动范围

- start_y_variance
  - 类型：int
  - 默认值：12
  - 最小值：0
  - 作用：起点 y 方向随机抖动范围

- end_y_variance
  - 类型：int
  - 默认值：18
  - 最小值：0
  - 作用：终点 y 方向随机抖动范围

- duration_min_ms
  - 类型：int
  - 默认值：80
  - 最小值：1

- duration_max_ms
  - 类型：int
  - 默认值：180
  - 规则：不得小于 duration_min_ms

- duration_ms
  - 类型：int
  - 兼容字段
  - 作用：旧配置兼容。若未配置 duration_min_ms / duration_max_ms，则按 duration_ms 固定时长执行

### 4.2 特殊写法

- 配置为 false：等价于 disabled
- activities 为空时：不会触发随机上滑

## 5. scenarios 字段说明

scenarios 是按顺序匹配的，命中第一个后执行动作并结束本轮场景判断。

### 5.1 场景字段

- name
  - 类型：string
  - 可选
  - 默认值：Scenario-N

- screen_text
  - 类型：string 或 array[string]
  - 必填（为空会被丢弃）
  - 作用：要求全部命中（AND 关系）

- screen_text_not_include
  - 类型：string 或 array[string]
  - 可选
  - 作用：若任一命中则判定场景不匹配

- scope
  - 类型：string
  - 可选
  - 值：top / center / bottom / top_left / top_right
  - 作用：限制 OCR 识别区域

- action
  - 类型：object
  - 可选
  - 作用：场景命中后的动作。不填则仅识别不操作

### 5.2 action.type 支持

- click_coords
  - 必填字段：x, y

- click_text
  - 必填字段：target
  - 可选字段：scope（当场景未配置 scope 时可在 action 内提供）

- swipe
  - 必填字段：start_x, start_y, end_x, end_y, duration_ms

- launch_app
  - 必填字段：package

说明：

- scope 使用优先级：scenario.scope 优先，其次 action.scope
- click_text 找到文字后，会点击识别框偏右位置（提升点击命中率）

## 6. 统一格式与默认值处理规则

配置加载时会自动进行规范化：

1. 类型修正
   - 数字字符串会转为 int
   - 非法数字会回退默认值

2. 边界修正
   - poll_interval_seconds、run_duration_minutes、各 duration 字段会强制最小值
   - max 字段会自动不小于 min 字段

3. 结构修正
   - app_loop 非法项会过滤
   - scenarios 中缺少有效 screen_text 的项会过滤
   - activities 支持 string 自动转单元素列表

4. 目录修正
   - screenshot_dir 不存在会自动创建

## 7. 推荐模板

### 7.1 settings_config.json 模板

{
  "adb_path": "adb",
  "adb_wifi_devices": [
    "192.168.1.23:5555",
    {
      "host": "192.168.1.24",
      "port": 5555,
      "auto_connect": true
    }
  ],
  "keep_scope_temp_images": false,
  "poll_interval_seconds": 3,
  "run_duration_minutes": 30,
  "screenshot_dir": "temp_screenshots",
  "app_loop": [
    {
      "device": {
        "id": "YOUR_DEVICE_ID",
        "name": "主设备",
        "test_icon_position_list": [
          {"x": 200, "y": 600},
          {"x": 500, "y": 600}
        ]
      }
    }
  ]
}

### 7.2 应用专属配置模板

{
  "_comment": "应用名称",
  "back_activities": [
    "com.example.app/.AdActivity"
  ],
  "activity_random_swipe_up": {
    "enabled": true,
    "activities": [
      "com.example.app/.HomeActivity"
    ],
    "interval_min_seconds": 10,
    "interval_max_seconds": 15,
    "start_x": 500,
    "start_y": 900,
    "end_x": 500,
    "end_y": 660,
    "x_variance": 20,
    "start_y_variance": 12,
    "end_y_variance": 18,
    "duration_min_ms": 80,
    "duration_max_ms": 180
  },
  "scenarios": [
    {
      "name": "示例：看广告领奖励",
      "scope": "center",
      "screen_text": [
        "看广告",
        "领奖励"
      ],
      "screen_text_not_include": [
        "明日再来"
      ],
      "action": {
        "type": "click_text",
        "target": "领奖励"
      }
    }
  ]
}

## 8. 常见问题

1. 为什么配置写了但没生效

- 先确认当前前台包名是否正确，是否命中对应 <包名>_config.json
- 再确认场景是否被前面规则抢先命中（scenarios 按顺序匹配）
- 检查 activity_random_swipe_up 是否提前触发并跳过了本轮 OCR

2. 如何做更稳定的 OCR

- 优先给场景加 scope
- 使用多个 screen_text 组合约束
- 善用 screen_text_not_include 排除相似界面

3. 多设备时如何配置 app_loop

- 仅给需要轮询切应用的设备配置 app_loop
- 未配置 app_loop 的设备会自动走简单监控模式

## 9. 最小可用配置（3 分钟上手）

本附录只保留必须字段，适合第一次跑通。

### 9.1 最小 settings_config.json

用途：单设备、无 app_loop、每 3 秒循环一次。

{
  "adb_path": "adb",
  "adb_wifi_devices": [],
  "poll_interval_seconds": 3,
  "screenshot_dir": "temp_screenshots"
}

说明：

- run_duration_minutes、app_loop、keep_scope_temp_images 都不是必填
- 不配置 app_loop 时，设备会自动使用简单监控模式

### 9.2 最小 config.json

用途：识别到一个关键字后点击另一个关键字。

{
  "scenarios": [
    {
      "name": "最小示例-点击领取",
      "screen_text": [
        "领取"
      ],
      "action": {
        "type": "click_text",
        "target": "领取"
      }
    }
  ]
}

说明：

- scenarios 是运行规则中的唯一必须字段
- 每个 scenario 里 screen_text 是必须字段（字符串或字符串数组都可以）
- action 可不填；不填表示只识别不执行动作

### 9.3 最小 app 专属配置（可选）

如果希望某个 App 用独立规则，新建同名文件：

- 文件名格式：<包名>_config.json
- 例如：com.example.app_config.json

最小内容仍然只需要 scenarios：

{
  "scenarios": [
    {
      "name": "App 专属最小示例",
      "screen_text": ["立即领取"],
      "action": {
        "type": "click_text",
        "target": "立即领取"
      }
    }
  ]
}

### 9.4 最小 activity_random_swipe_up（可选）

如果只想在指定 Activity 下自动上滑，不做额外 OCR 规则，可这样写：

{
  "activity_random_swipe_up": {
    "enabled": true,
    "activities": [
      "com.example.app/.HomeActivity"
    ]
  },
  "scenarios": [
    {
      "name": "兜底示例",
      "screen_text": ["领取"],
      "action": {
        "type": "click_text",
        "target": "领取"
      }
    }
  ]
}

说明：

- 只写 enabled + activities 即可，其余参数会走默认值
- 命中后会随机等待（默认 10-15 秒）再执行上滑，并跳过本轮 OCR 处理

### 9.5 新人快速检查清单

1. adb devices 能看到设备
2. settings_config.json 至少有 adb_path、poll_interval_seconds、screenshot_dir
3. config.json 至少有一个 scenarios 项，且 screen_text 不为空
4. 运行程序后确认日志中能看到设备被处理

### 9.6 最小 Wi-Fi 无线调试配置（可选）

如果你已经在 Android 设备上开启了无线调试，并拿到了 `IP:端口`，只需要在 settings_config.json 中加上：

{
  "adb_path": "adb",
  "adb_wifi_devices": [
    "192.168.1.23:5555"
  ],
  "poll_interval_seconds": 3,
  "screenshot_dir": "temp_screenshots"
}

说明：

- 程序启动和轮询过程中会自动尝试 `adb connect 192.168.1.23:5555`
- 如果该设备同时也通过 USB 连接，ADB 会同时显示两个 serial，这是正常现象

## 10. 调试脚本

### 10.1 test.py

用途：

- 截取所有当前连接设备的屏幕
- OCR 分析所有文字
- 控制台输出识别结果
- 保存 OCR 结果到 `ocr_report.json`

### 10.2 test_adb_wifi.py

用途：

- 单独测试 settings_config.json 中配置的 `adb_wifi_devices`
- 自动执行 `adb connect`
- 检查设备是否出现在 `adb devices`
- 获取当前前台应用与当前 Activity
- 测试截图是否成功
- 输出结果到控制台并保存到 `adb_wifi_report.json`

示例：

```bash
python test_adb_wifi.py
python test_adb_wifi.py --cleanup
python test_adb_wifi.py --output-dir wifi_test_screenshots --save-json adb_wifi_report.json
```

## 11. 打包与安装包构建

本项目已提供完整打包流水线，可在 Windows 上生成：

1. 目录包（PyInstaller 输出）
2. 安装包（Inno Setup 输出 .exe）

### 11.1 前置条件

1. Windows 环境
2. 可用的 Python（建议使用项目 `.venv`）
3. 已安装 Inno Setup 6（需有 `ISCC.exe`）

说明：

- `build.ps1` 会自动安装/更新 PyInstaller
- 若本地没有 `platform-tools/adb.exe`，脚本会自动下载 Android platform-tools

### 11.2 一键构建命令

在项目根目录执行：

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\packaging\build.ps1 -Version 1.0.0
```

### 11.3 可选参数

- `-Version 1.0.0`
  - 设置安装包版本号（会体现在安装包文件名中）

- `-SkipInstaller`
  - 仅构建目录包，不生成安装包

- `-SkipPlatformToolsDownload`
  - 跳过 platform-tools 自动下载（要求你已在项目中准备好可用 adb）

示例：

```powershell
# 只生成目录包
.\packaging\build.ps1 -Version 1.0.0 -SkipInstaller

# 不下载 platform-tools（离线构建）
.\packaging\build.ps1 -Version 1.0.0 -SkipPlatformToolsDownload
```

### 11.4 构建产物位置

- PyInstaller 目录包：`dist/ScreenWatcher`
- 安装包：`packaging/output/ScreenWatcher-Setup-<Version>.exe`

### 11.5 运行时目录说明（安装后）

安装包采用 per-user 安装策略，默认安装到：

- `{localappdata}\Programs\ScreenWatcher`

程序运行时会使用用户数据目录：

- `%LOCALAPPDATA%\ScreenWatcher`

该目录下会保存：

- `settings_config.json`
- `config.json`
- `app_configs/`
- `temp_screenshots/`

默认行为会保留用户数据（便于升级后保留配置）；卸载时仅在勾选清理用户数据选项时才删除。

### 11.6 常见问题

1. 提示 `ISCC.exe was not found`

- 说明未安装 Inno Setup 或路径未被识别
- 安装 Inno Setup 6 后重试

2. 能生成目录包，不能生成安装包

- 通常是 Inno Setup 阶段失败
- 先用 `-SkipInstaller` 验证 PyInstaller 是否正常

3. 目标机启动后 OCR 无法工作

- 目标机需安装对应 OCR 语言包（如 `zh-Hans-CN`）
- 这是系统能力依赖，不是打包失败
