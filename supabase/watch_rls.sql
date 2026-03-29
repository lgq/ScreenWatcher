-- RLS 策略示例（V1）
-- 约定：
-- 1) Android 发布端 JWT 携带 app_role=config_admin。
-- 2) PC 端 JWT 携带 device_id=<本机 device_id>。
-- 3) 三张表都启用 RLS，避免匿名越权访问。

alter table public.watch_config_versions enable row level security;
alter table public.watch_devices enable row level security;
alter table public.watch_device_status_logs enable row level security;

-- -------- watch_config_versions --------
-- 所有已认证客户端可读取当前配置版本（通常由服务端过滤 is_active=true）。
drop policy if exists watch_config_versions_select_authenticated on public.watch_config_versions;
create policy watch_config_versions_select_authenticated
on public.watch_config_versions
for select
to authenticated
using (true);

-- 仅配置发布端可写入/修改配置版本。
drop policy if exists watch_config_versions_write_admin on public.watch_config_versions;
create policy watch_config_versions_write_admin
on public.watch_config_versions
for all
to authenticated
using (coalesce(auth.jwt() ->> 'app_role', '') = 'config_admin')
with check (coalesce(auth.jwt() ->> 'app_role', '') = 'config_admin');

-- -------- watch_devices --------
-- 已认证客户端可查看设备最新状态（便于控制端总览）。
drop policy if exists watch_devices_select_authenticated on public.watch_devices;
create policy watch_devices_select_authenticated
on public.watch_devices
for select
to authenticated
using (true);

-- PC 端只能写自己的 device_id 行。
drop policy if exists watch_devices_upsert_self on public.watch_devices;
create policy watch_devices_upsert_self
on public.watch_devices
for insert
to authenticated
with check (device_id = coalesce(auth.jwt() ->> 'device_id', ''));

drop policy if exists watch_devices_update_self on public.watch_devices;
create policy watch_devices_update_self
on public.watch_devices
for update
to authenticated
using (device_id = coalesce(auth.jwt() ->> 'device_id', ''))
with check (device_id = coalesce(auth.jwt() ->> 'device_id', ''));

-- -------- watch_device_status_logs --------
-- 控制端可读历史日志；普通 PC 端不需要读全量日志。
drop policy if exists watch_device_status_logs_select_admin on public.watch_device_status_logs;
create policy watch_device_status_logs_select_admin
on public.watch_device_status_logs
for select
to authenticated
using (
    coalesce(auth.jwt() ->> 'app_role', '') = 'config_admin'
    or device_id = coalesce(auth.jwt() ->> 'device_id', '')
);

-- PC 端只能插入自己的日志。
drop policy if exists watch_device_status_logs_insert_self on public.watch_device_status_logs;
create policy watch_device_status_logs_insert_self
on public.watch_device_status_logs
for insert
to authenticated
with check (device_id = coalesce(auth.jwt() ->> 'device_id', ''));

-- 建议：上线前根据实际 JWT 结构调整 app_role/device_id 的 claim 名称。