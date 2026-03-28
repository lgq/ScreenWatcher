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

- app_loop
  - 类型：array
  - 默认值：[]
  - 作用：为指定设备启用“应用轮询监控”

### 2.2 app_loop 元素结构

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
