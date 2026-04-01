import copy
import hashlib
import json
from typing import Any, Dict, Tuple


CURRENT_SCHEMA_VERSION = 1
ALLOWED_MONITOR_STATES = {"running", "paused"}


def canonical_json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def compute_bundle_hash(bundle: Dict[str, Any]) -> str:
    payload = copy.deepcopy(bundle)
    protocol = payload.get("protocol") if isinstance(payload.get("protocol"), dict) else {}
    normalized_protocol = dict(protocol)
    # hash 字段本身不能参与哈希计算，否则每次计算结果都会变化。
    normalized_protocol.pop("hash", None)
    payload["protocol"] = normalized_protocol
    digest = hashlib.sha256(canonical_json_dumps(payload).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def normalize_control(control: Any) -> Dict[str, Any]:
    config = control if isinstance(control, dict) else {}
    monitor_state = str(config.get("monitor_state", "running")).strip().lower() or "running"
    if monitor_state not in ALLOWED_MONITOR_STATES:
        monitor_state = "running"

    return {
        "enabled": bool(config.get("enabled", True)),
        "monitor_state": monitor_state,
        "poll_interval_seconds": max(5, int(config.get("poll_interval_seconds", 10) or 10)),
        "status_upload_interval_seconds": max(5, int(config.get("status_upload_interval_seconds", 10) or 10)),
    }


def validate_remote_bundle(bundle: Any, project_id: str) -> Tuple[Dict[str, Any], str]:
    if not isinstance(bundle, dict):
        return {}, "远程配置不是 JSON 对象"

    protocol = bundle.get("protocol") if isinstance(bundle.get("protocol"), dict) else {}
    remote_project_id = str(protocol.get("project_id", project_id)).strip() or project_id
    if remote_project_id != project_id:
        return {}, f"project_id 不匹配: {remote_project_id}"

    try:
        revision = int(protocol.get("revision", 0) or 0)
    except (TypeError, ValueError):
        return {}, "revision 非法"
    if revision <= 0:
        return {}, "revision 必须大于 0"

    try:
        schema_version = int(protocol.get("schema_version", CURRENT_SCHEMA_VERSION) or CURRENT_SCHEMA_VERSION)
    except (TypeError, ValueError):
        return {}, "schema_version 非法"
    if schema_version != CURRENT_SCHEMA_VERSION:
        return {}, f"不支持的 schema_version: {schema_version}"

    settings_config = bundle.get("settings_config")
    if not isinstance(settings_config, dict):
        return {}, "settings_config 必须为对象"

    config_json = bundle.get("config_json")
    if not isinstance(config_json, dict):
        return {}, "config_json 必须为对象"

    app_configs_raw = bundle.get("app_configs", {})
    if not isinstance(app_configs_raw, dict):
        return {}, "app_configs 必须为对象"

    app_configs: Dict[str, Dict[str, Any]] = {}
    for package_name, config in app_configs_raw.items():
        normalized_package = str(package_name).strip()
        if not normalized_package or not isinstance(config, dict):
            continue
        app_configs[normalized_package] = config

    # 先做结构归一化，再统一校验 hash，避免客户端因为字段顺序不同误判配置变更。
    normalized = {
        "protocol": {
            "schema_version": schema_version,
            "project_id": remote_project_id,
            "revision": revision,
            "created_at": str(protocol.get("created_at", "")).strip(),
            "author": str(protocol.get("author", "")).strip(),
            "hash": str(protocol.get("hash", "")).strip(),
            "effective_mode": str(protocol.get("effective_mode", "immediate")).strip() or "immediate",
            "min_client_version": str(protocol.get("min_client_version", "")).strip(),
        },
        "control": normalize_control(bundle.get("control", {})),
        "settings_config": settings_config,
        "config_json": config_json,
        "app_configs": app_configs,
    }

    expected_hash = normalized["protocol"].get("hash", "")
    if expected_hash:
        actual_hash = compute_bundle_hash(normalized)
        if actual_hash != expected_hash:
            return {}, f"配置哈希不匹配: expected={expected_hash}, actual={actual_hash}"

    return normalized, ""