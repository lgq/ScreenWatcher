# task_engine_v2 远程控制方案 V1（Android + Supabase + PC）

## 1. 目标与边界

目标：
- Android 控制端可拉取最新配置、编辑并发布生效。
- PC 端 task_engine_v2 每 10 秒同步配置，发现新版本后自动应用。
- PC 端每 10 秒上报运行状态（设备连接、电池、屏幕、任务状态）。
- 服务端统一以 Supabase 为配置真源。

边界：
- 本方案完全在 task_engine_v2 目录内实现，不复用既有 remote 实现代码。
- V1 采用轮询，不依赖 Realtime。
- 配置以完整快照发布，不做 patch 增量合并。

---

## 2. 总体架构

组件：
- Android App（控制端）
  - 读取 active 配置
  - 编辑后发布新 revision
- Supabase（配置与状态中心）
  - 保存配置版本
  - 保存设备当前状态和状态日志
- task_engine_v2（执行端）
  - 拉取配置并应用
  - 按配置控制调度器暂停/继续
  - 上报设备状态

核心原则：
- 配置协议和状态协议分离。
- 发布配置必须生成新 revision，旧版本不可改写。
- PC 端只接受 revision 严格递增的配置。
- 本地应用配置采用 临时文件 + 校验 + 原子替换。

---

## 3. 配置协议（RemoteConfigBundle）

建议 JSON 结构（服务端 config_json 字段存储完整对象）：

{
  "meta": {
    "schema_version": 1,
    "project_id": "screenwatcher-prod",
    "revision": 12,
    "created_at": "2026-04-01T08:00:00Z",
    "author": {
      "user_id": "u_1001",
      "name": "admin"
    },
    "content_hash": "sha256:...",
    "min_pc_version": "2.0.0"
  },
  "control": {
    "enabled": true,
    "engine_state": "running",
    "config_pull_interval_sec": 10,
    "status_push_interval_sec": 10,
    "apply_mode": "immediate"
  },
  "task_engine": {
    "assignments": {
      "assignments": [
        {
          "device_id": "N0URB50103",
          "task_file": "tasks/douying_watch_video.json",
          "need_loop": true
        }
      ]
    },
    "task_files": {
      "tasks/douying_watch_video.json": {
        "name": "douyin_watch_video",
        "entry": { "start_from_home": true, "steps": [] },
        "execute": {
          "poll_interval_seconds": 5,
          "required_activities": [],
          "screenshot_dir": "task_engine_v2/screenshots",
          "scenarios": []
        },
        "exit": { "max_duration_seconds": 1800, "stop_on_action_types": [] }
      }
    }
  },
  "safety": {
    "allow_remote_stop": true,
    "max_task_duration_seconds": 7200,
    "graceful_stop_timeout_seconds": 15
  }
}

字段约束：
- meta.schema_version：协议版本，V1 固定为 1。
- meta.project_id：项目标识，PC 必须与本地 project_id 一致。
- meta.revision：必须单调递增。
- meta.content_hash：对去除该字段后的完整 JSON 做稳定序列化后计算 sha256。
- control.engine_state：running 或 paused。
- control.enabled=false 时，PC 禁用远控，只保留本地配置执行。
- task_engine.assignments 与 task_files 必须自洽：assignments.task_file 必须在 task_files 中出现。

---

## 4. 状态协议（DeviceStatusSnapshot）

建议每 10 秒上报：

{
  "project_id": "screenwatcher-prod",
  "pc_id": "pc-001",
  "reported_at": "2026-04-01T08:00:10Z",
  "runtime": {
    "engine_state": "running",
    "remote_enabled": true,
    "last_applied_revision": 12,
    "apply_status": "success",
    "apply_error": ""
  },
  "host": {
    "hostname": "DESKTOP-123",
    "ip": "192.168.0.12",
    "app_version": "2.0.0"
  },
  "phones": [
    {
      "device_id": "N0URB50103",
      "connected": true,
      "battery_percent": 86,
      "screen_on": true,
      "current_task": "douyin_watch_video",
      "task_state": "running",
      "last_error": ""
    }
  ]
}

字段约束：
- phones 可为空数组（表示当前无手机连接）。
- battery_percent 可为 null（取值失败时）。
- task_state 取值：idle, running, paused, error。
- apply_status 取值：success, failed, skipped。

---

## 5. Supabase 数据模型

建议表：

1) te2_config_versions（配置版本表）
- id uuid pk
- project_id text not null
- revision bigint not null
- is_active boolean not null default false
- config_json jsonb not null
- content_hash text not null
- schema_version int not null
- author_user_id text
- author_name text
- publish_note text
- created_at timestamptz default now()

约束：
- unique(project_id, revision)
- 每个 project_id 仅一条 is_active=true（可用部分唯一索引）

2) te2_device_runtime（设备当前状态表）
- project_id text not null
- pc_id text not null
- updated_at timestamptz not null
- last_seen_at timestamptz not null
- last_applied_revision bigint
- engine_state text
- apply_status text
- apply_error text
- phones jsonb
- primary key(project_id, pc_id)

3) te2_device_status_logs（设备状态日志表）
- id uuid pk
- project_id text not null
- pc_id text not null
- reported_at timestamptz not null
- last_applied_revision bigint
- engine_state text
- payload jsonb not null

建议 RPC：
- te2_publish_config(project_id, base_revision, new_config_json, note)
  - 事务内执行：revision+1、新增版本、切换 is_active。
  - 若 base_revision 非当前 active，返回冲突。

---

## 6. Android 控制端流程

打开页面：
1. 查询 te2_config_versions 中 project_id 对应 active 配置。
2. 显示 revision 和配置内容。
3. 允许编辑 task_engine.assignments / task_files / control 字段。

点击 生效：
1. 本地校验（schema、必填项、自洽性）。
2. 重新计算 content_hash。
3. 调用 te2_publish_config，携带 base_revision（当前看到的 revision）。
4. 若冲突（期间别人已发布），提示用户重新拉取并合并。

建议交互：
- 发布前弹窗展示 diff 摘要。
- 发布成功后显示 新 revision。

---

## 7. PC 执行端流程（task_engine_v2）

每 10 秒执行一个同步周期：
1. 拉取 active 配置（project_id 过滤）。
2. 如果 revision <= last_applied_revision：跳过应用，仅上报状态。
3. revision 更新时执行 apply：
   - 校验 project_id/schema_version/revision/content_hash。
   - 校验 assignments 与 task_files 自洽。
   - 将配置写入 staging 目录。
   - 原子替换 runtime 生效配置。
   - 更新本地 remote_state.json。
4. 将本周期状态上报 te2_device_runtime（upsert）。
5. 追加一条 te2_device_status_logs 日志。

建议本地目录：
- task_engine_v2/runtime/remote/remote_state.json
- task_engine_v2/runtime/remote/active/assignments.json
- task_engine_v2/runtime/remote/active/tasks/*.json
- task_engine_v2/runtime/remote/staging/rev_<revision>/...
- task_engine_v2/runtime/remote/backups/rev_<revision>/...

---

## 8. 调度器控制语义

remote control 对调度器的影响：
- enabled=false：不接收远端控制，按本地静态配置运行。
- engine_state=paused：
  - 不再启动新设备线程。
  - 已在执行中的任务发出 graceful stop 信号。
  - 超过 graceful_stop_timeout_seconds 后强制结束。
- engine_state=running：恢复调度。

建议在 scheduler 中增加：
- 全局控制状态对象（线程安全）。
- 每轮循环读取当前控制状态。
- TaskRunner 内部周期性检查 stop_token。

---

## 9. 模块划分（全部在 task_engine_v2 下）

建议新增目录：
- task_engine_v2/remote/
  - protocol.py（协议模型、校验、hash）
  - supabase_client.py（REST/RPC 封装）
  - config_sync.py（拉取、比较、应用、回滚）
  - status_collector.py（设备状态采集）
  - status_reporter.py（状态上报）
  - control_state.py（运行态与 stop token）
  - remote_loop.py（每 10 秒调度循环）

与现有引擎集成点：
- run.py：初始化 RemoteLoop 和 Scheduler。
- scheduler.py：读取 control_state，决定是否拉起/暂停。
- task_runner.py：检查 stop_token 并快速退出。
- models.py：增加远程配置到本地 assignments/task 文件的加载入口。

---

## 10. 异常与回滚策略

配置应用失败：
- 不覆盖 active 本地配置。
- 记录 apply_status=failed 与 apply_error。
- 状态继续上报，便于控制端看到失败原因。

网络失败：
- 本地继续使用上一次成功配置运行。
- 标记 last_sync_error，下一周期重试。

配置冲突：
- Android 发布时基于 base_revision CAS。
- 冲突返回后由用户重新拉取再发布。

数据损坏：
- hash 校验失败直接拒绝应用。
- 保留备份，写日志并上报。

---

## 11. 安全与权限建议

- Android：使用 Supabase Auth 登录用户。
- PC：建议用专用受限 key，仅允许：
  - 读 te2_config_versions active
  - 写 te2_device_runtime 与 te2_device_status_logs
- 启用 RLS，按 project_id 与 pc_id 限制访问范围。

---

## 12. 分阶段实施计划

Phase 1（最小可用）：
- 完成协议模型、Supabase 表、Android 拉取和发布。
- PC 端完成轮询拉取 + 本地应用 + revision 记录。

Phase 2（运行控制）：
- 接入 scheduler 的 paused/running 控制。
- 接入 graceful stop 机制。

Phase 3（状态闭环）：
- 完成状态采集与双写上报（runtime + logs）。
- Android 增加设备状态面板。

Phase 4（工程化）：
- 增加单元测试、集成测试、故障注入测试。
- 增加审计字段、发布注释、灰度 project。

---

## 13. 验收标准（V1）

- Android 发布新配置后，PC 在 10-20 秒内应用成功。
- 配置非法时，PC 不会破坏当前运行配置，并能回传失败原因。
- paused 指令下发后，PC 可在可接受时限内停止任务。
- 设备状态可在 Android 端稳定看到，刷新周期不超过 10 秒。
- 断网恢复后，PC 能自动继续同步并追上最新 revision。
