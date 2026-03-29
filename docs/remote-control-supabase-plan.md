# ScreenWatcher 远程控制方案（Supabase）

本文档面向维护者，描述当前远控 V1 的协议、数据模型和 ScreenWatcher 落地方式。
设计原则是先实现“配置可下发、状态可回传、异常可回滚”，再逐步增强实时性与权限隔离。

## 1. 目标

- Android 控制端启动后从 Supabase 拉取最新配置并展示。
- 用户修改配置并点击生效后，控制端将完整配置快照发布为一个新版本。
- PC 端 ScreenWatcher 每 10 秒轮询 Supabase，发现新配置后下载、校验并原子替换本地配置。
- PC 端每 10 秒上报设备连接状态、电量、屏幕状态、当前配置版本和运行状态。
- 配置更新失败时保留旧配置继续运行，并把错误回传到服务端。

## 2. 总体架构

1. Supabase 保存配置版本、PC 在线状态和状态日志。
2. Android App 是配置编辑端，只负责读取最新配置、编辑、发布。
3. ScreenWatcher 是配置执行端，负责轮询、应用配置和上报状态。
4. 配置采用版本化协议，状态采用独立快照协议。

说明：

- Android 端当前只需要遵守协议，不要求与 PC 端共享代码。
- PC 端先采用轮询实现，后续如需降低延迟，可再叠加 Supabase Realtime。

## 3. Supabase 表设计

### 3.1 watch_config_versions

- id: uuid
- project_id: text
- revision: bigint
- config_json: jsonb
- config_hash: text
- schema_version: integer
- author_user_id: text
- author_name: text
- publish_note: text
- created_at: timestamptz
- is_active: boolean

约束建议：

- unique(project_id, revision)
- 同一 project_id 仅允许一个 is_active=true

用途说明：

- 该表保存完整配置快照，而不是增量 patch，便于 PC 端直接下载并做整包校验。
- is_active 用于标识当前发布生效版本，避免 PC 端自行决定“最新版本”。

### 3.2 watch_devices

- device_id: text
- device_name: text
- app_version: text
- config_revision_applied: bigint
- config_apply_status: text
- config_apply_error: text
- monitor_state: text
- last_seen_at: timestamptz
- updated_at: timestamptz

用途说明：

- 该表保存每台 PC 的最新状态，适合 Android 控制端做总览列表。
- config_apply_status 和 config_apply_error 用于显示配置是否真正落地成功。

### 3.3 watch_device_status_logs

- id: uuid
- device_id: text
- status_time: timestamptz
- config_revision_applied: bigint
- monitor_state: text
- screenwatcher_state: text
- phones: jsonb
- network_ok: boolean
- extra: jsonb

用途说明：

- 该表保存按时间序列累积的状态快照，适合排障、审计和后续统计。
- 若后期日志量增长较大，可按时间做归档或分区。

## 4. 配置协议

服务端保存的 config_json 使用如下协议：

```json
{
  "protocol": {
    "schema_version": 1,
    "project_id": "screenwatcher-prod",
    "revision": 106,
    "created_at": "2026-03-29T12:00:00Z",
    "author": "android-user-001",
    "hash": "sha256:xxxx",
    "effective_mode": "immediate",
    "min_client_version": "1.0.6"
  },
  "control": {
    "enabled": true,
    "monitor_state": "running",
    "poll_interval_seconds": 10,
    "status_upload_interval_seconds": 10
  },
  "settings_config": {
    "adb_path": "adb",
    "adb_wifi_devices": [],
    "keep_scope_temp_images": false,
    "poll_interval_seconds": 3,
    "run_duration_minutes": 60,
    "screenshot_dir": "temp_screenshots"
  },
  "config_json": {
    "scenarios": []
  },
  "app_configs": {
    "com.ss.android.ugc.aweme.lite": {
      "scenarios": []
    }
  }
}
```

规则：

- ScreenWatcher 只接受 revision 严格大于本地已应用 revision 的配置。
- hash 计算范围为整个 config_json 主体内容。
- settings_config 不包含 PC 本地专属的远控连接信息，避免远端配置覆盖本地 Supabase 凭据。
- control.monitor_state 仅允许 running 和 paused。

实现说明：

- protocol.hash 由客户端对整个 bundle 做稳定序列化后计算 sha256。
- ScreenWatcher 在写本地配置前必须先校验 project_id、schema_version、revision 和 hash。
- 即使服务端返回了新配置，若 revision 未前进，也不会重复覆盖本地文件。

## 5. ScreenWatcher 本地文件布局

新增以下运行时文件：

- remote_control_state.json
  - 保存最近一次已应用 revision、apply 状态、错误信息、最后同步时间。
- device_status.json
  - 保存最近一次采集到的本地设备状态快照。
- backups/remote_config_revision_<revision>/
  - 保存已应用版本快照，便于回滚。

说明：

- 当前实现中，远端配置会拆回本地 settings_config.json、config.json 和各 app 专属配置文件。
- remote_control 自身连接参数保留本机版本，不会被服务端 settings_config 覆盖。

## 6. ScreenWatcher 同步流程

每 10 秒执行一次：

1. 从 Supabase 拉取当前 project_id 的 active 配置。
2. 比较 revision：若未变化则跳过配置应用。
3. 若有新版本：
   - 校验 schema_version、project_id、revision、control 和 hash。
   - 将 settings_config、config_json、各 app_configs 写入临时文件。
   - 备份当前配置。
   - 原子替换目标文件。
   - 更新 remote_control_state.json。
4. 采集当前设备状态并写入 device_status.json。
5. 将 watch_devices 最新状态与 watch_device_status_logs 日志上传到 Supabase。

异常处理约定：

- 配置校验失败时，保留旧配置继续运行，并把失败原因写入 remote_control_state.json。
- 状态上报失败不会中断监控主循环，只会在本地状态文件中记录最近错误。
- 本地配置写入采用临时文件 + 原子替换，避免产生半写入文件。

## 7. 运行控制

- control.monitor_state=running：正常监控。
- control.monitor_state=paused：ScreenWatcher 不创建新设备任务，并取消当前监控任务。
- control.enabled=false：远控关闭，ScreenWatcher 只使用本地配置。

## 8. 安全建议

- Android 使用用户登录态发布配置。
- PC 端只允许读取 active 配置、写入自己的状态。
- 正式环境建议使用受限 token 和 RLS，而不是无约束 service role key。

建议顺序：

1. 先在测试项目中验证表结构和协议。
2. 再为 PC 端创建受限访问策略，只允许写自己的 device_id。
3. 最后再接入 Android 登录态与正式发布流程。

## 9. V1 实施范围

- 在 ScreenWatcher 内实现基于 Supabase REST 的轮询同步。
- 实现配置下发、状态回传、暂停/继续控制。
- Android 端暂不在本仓库内实现，只对接协议和数据模型。

## 10. 初始化步骤

1. 在 Supabase SQL Editor 执行 [supabase/watch_schema.sql](../supabase/watch_schema.sql)。
2. 执行 [supabase/watch_rls.sql](../supabase/watch_rls.sql) 并按你的 JWT claim 实际字段微调策略。
3. 在 ScreenWatcher 的 settings_config.json 中填写 remote_control 下的 supabase_url、supabase_key、project_id、device_id。
4. 运行命令生成初始配置 SQL：

```bash
python supabase/generate_seed_sql.py --revision 1 --author admin
```

5. 在 Supabase SQL Editor 执行生成的 [supabase/seed_active_config.sql](../supabase/seed_active_config.sql)。
6. 启动 ScreenWatcher，检查本地生成的 remote_control_state.json 与 device_status.json 是否正常更新。

## 11. 联调检查清单

1. watch_config_versions 中是否存在且仅存在一条 is_active=true 的记录。
2. remote_control_state.json 中 last_applied_revision 是否从 0 变为服务端 revision。
3. watch_devices 是否出现当前 device_id 的 upsert 记录。
4. watch_device_status_logs 是否持续新增状态快照。
5. 当服务端 control.monitor_state 改为 paused 后，PC 是否停止监控任务。