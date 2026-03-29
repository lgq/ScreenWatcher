-- 远控 V1 依赖 pgcrypto 生成 uuid 主键。
create extension if not exists pgcrypto;

-- 保存配置快照版本。Android 每次“发布生效”都会写入一条新记录。
create table if not exists public.watch_config_versions (
    id uuid primary key default gen_random_uuid(),
    project_id text not null,
    revision bigint not null,
    config_json jsonb not null,
    config_hash text not null default '',
    schema_version integer not null default 1,
    author_user_id text not null default '',
    author_name text not null default '',
    publish_note text not null default '',
    created_at timestamptz not null default timezone('utc', now()),
    is_active boolean not null default false,
    unique (project_id, revision)
);

-- 同一个 project 同时只能有一个 active 版本，PC 端轮询时只读取该版本。
create unique index if not exists watch_config_versions_active_idx
    on public.watch_config_versions (project_id)
    where is_active = true;

-- 保存每台 PC 的最新状态，适合控制端直接展示“当前在线设备列表”。
create table if not exists public.watch_devices (
    device_id text primary key,
    device_name text not null default '',
    app_version text not null default '',
    config_revision_applied bigint not null default 0,
    config_apply_status text not null default 'never',
    config_apply_error text not null default '',
    monitor_state text not null default 'running',
    last_seen_at timestamptz not null default timezone('utc', now()),
    updated_at timestamptz not null default timezone('utc', now())
);

-- 保存周期性状态日志，适合排查问题和后续做统计分析。
create table if not exists public.watch_device_status_logs (
    id uuid primary key default gen_random_uuid(),
    device_id text not null,
    status_time timestamptz not null default timezone('utc', now()),
    config_revision_applied bigint not null default 0,
    monitor_state text not null default 'running',
    screenwatcher_state text not null default 'healthy',
    phones jsonb not null default '[]'::jsonb,
    network_ok boolean not null default true,
    extra jsonb not null default '{}'::jsonb
);

-- 建议后续补充：
-- 1. 针对 watch_devices.device_id、watch_device_status_logs.device_id 配置 RLS。
-- 2. 按 status_time 为 watch_device_status_logs 增加索引。
-- 3. 在正式环境中仅允许 Android 发布端写 watch_config_versions。