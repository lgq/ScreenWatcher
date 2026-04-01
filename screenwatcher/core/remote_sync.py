import json
import os
import socket
import tempfile
import time
from datetime import datetime, timezone
from typing import Any, Dict, List
from urllib import error, parse, request

import adb_util

from . import __version__, runtime_paths
from .config_service import ConfigService
from .remote_protocol import validate_remote_bundle


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _safe_read_json(path: str, default: Dict[str, Any]) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as file:
            data = json.load(file)
            return data if isinstance(data, dict) else default
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def _atomic_write_json(path: str, payload: Dict[str, Any]) -> None:
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", delete=False, dir=directory, encoding="utf-8") as tmp:
        json.dump(payload, tmp, ensure_ascii=False, indent=2)
        temp_path = tmp.name
    # 通过 os.replace 做原子替换，避免程序在写配置过程中留下半文件。
    os.replace(temp_path, path)


class SupabaseRestClient:
    def __init__(self, base_url: str, api_key: str, access_token: str = ""):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.access_token = access_token or api_key

    def _request(self, method: str, path: str, payload: Any = None, headers: Dict[str, str] | None = None) -> Any:
        request_headers = {
            "apikey": self.api_key,
            "Authorization": f"Bearer {self.access_token}",
            "Accept": "application/json",
        }
        if headers:
            request_headers.update(headers)

        data = None
        if payload is not None:
            request_headers["Content-Type"] = "application/json"
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")

        req = request.Request(f"{self.base_url}{path}", data=data, headers=request_headers, method=method)
        with request.urlopen(req, timeout=15) as response:
            raw_body = response.read().decode("utf-8")
            if not raw_body:
                return None
            return json.loads(raw_body)

    def fetch_active_config(self, table: str, project_id: str) -> Dict[str, Any]:
        encoded_project_id = parse.quote(project_id, safe="")
        path = (
            f"/rest/v1/{table}?project_id=eq.{encoded_project_id}&is_active=eq.true"
            "&select=revision,config_json,config_hash,schema_version,created_at"
            "&order=revision.desc&limit=1"
        )
        rows = self._request("GET", path)
        if isinstance(rows, list) and rows:
            return rows[0]
        return {}

    def upsert_device(self, table: str, payload: Dict[str, Any]) -> None:
        path = f"/rest/v1/{table}?on_conflict=device_id"
        self._request(
            "POST",
            path,
            [payload],
            headers={
                "Prefer": "resolution=merge-duplicates,return=minimal",
            },
        )

    def insert_status_log(self, table: str, payload: Dict[str, Any]) -> None:
        path = f"/rest/v1/{table}"
        self._request("POST", path, payload, headers={"Prefer": "return=minimal"})


class RemoteControlService:
    def __init__(self, config_service: ConfigService):
        self.config_service = config_service
        self.state_path = runtime_paths.get_runtime_file_path("remote_control_state.json")
        self.status_path = runtime_paths.get_runtime_file_path("device_status.json")
        self._last_config_poll = 0.0
        self._last_status_upload = 0.0

    def _load_raw_settings(self) -> Dict[str, Any]:
        return _safe_read_json(self.config_service.settings_path, {})

    def _read_state(self) -> Dict[str, Any]:
        return _safe_read_json(
            self.state_path,
            {
                "last_applied_revision": 0,
                "last_sync_at": "",
                "apply_status": "never",
                "apply_error": "",
                "control": {
                    "enabled": True,
                    "monitor_state": "running",
                    "poll_interval_seconds": 10,
                    "status_upload_interval_seconds": 10,
                },
            },
        )

    def _write_state(self, state: Dict[str, Any]) -> None:
        _atomic_write_json(self.state_path, state)

    def get_monitor_state(self) -> str:
        settings = self.config_service.load_settings()
        remote_settings = settings.get("remote_control", {})
        if not remote_settings.get("enabled"):
            return "running"

        state = self._read_state()
        control = state.get("control", {}) if isinstance(state.get("control"), dict) else {}
        if not bool(control.get("enabled", True)):
            return "running"
        return str(control.get("monitor_state", "running")).strip().lower() or "running"

    def run_cycle(self, active_monitor_devices: List[str]) -> None:
        settings = self.config_service.load_settings()
        remote_settings = settings.get("remote_control", {})
        if not remote_settings.get("enabled"):
            return
        if not remote_settings.get("supabase_url") or not remote_settings.get("supabase_key"):
            return

        now = time.monotonic()
        should_poll_config = now - self._last_config_poll >= remote_settings.get("config_poll_seconds", 10)
        should_upload_status = now - self._last_status_upload >= remote_settings.get("status_upload_seconds", 10)
        if not should_poll_config and not should_upload_status:
            return

        client = SupabaseRestClient(
            remote_settings["supabase_url"],
            remote_settings["supabase_key"],
            remote_settings.get("access_token", ""),
        )

        state = self._read_state()
        network_ok = True
        if should_poll_config:
            try:
                # 配置同步和状态上报拆成两套节流，避免状态频率被配置拉取拖慢。
                active_config = client.fetch_active_config(remote_settings["config_table"], remote_settings["project_id"])
                if active_config:
                    state = self._sync_remote_configuration(active_config, settings, state)
                self._last_config_poll = now
            except (error.URLError, TimeoutError, ValueError, OSError) as exc:
                network_ok = False
                state["last_sync_at"] = _utc_now_iso()
                state["apply_error"] = f"sync_failed: {exc}"
                self._write_state(state)

        if not should_upload_status:
            return
        status_snapshot = self._collect_status_snapshot(settings, state, active_monitor_devices, network_ok)
        _atomic_write_json(self.status_path, status_snapshot)

        try:
            client.upsert_device(remote_settings["device_table"], self._build_device_payload(status_snapshot, state, remote_settings))
            client.insert_status_log(remote_settings["status_table"], status_snapshot)
            self._last_status_upload = now
        except (error.URLError, TimeoutError, ValueError, OSError) as exc:
            status_snapshot["network_ok"] = False
            status_snapshot.setdefault("extra", {})["status_upload_error"] = str(exc)
            _atomic_write_json(self.status_path, status_snapshot)

    def _sync_remote_configuration(
        self,
        active_config: Dict[str, Any],
        normalized_settings: Dict[str, Any],
        state: Dict[str, Any],
    ) -> Dict[str, Any]:
        project_id = normalized_settings.get("remote_control", {}).get("project_id", "screenwatcher-prod")
        bundle, error_message = validate_remote_bundle(active_config.get("config_json", {}), project_id)
        now_iso = _utc_now_iso()

        if error_message:
            state["last_sync_at"] = now_iso
            state["apply_status"] = "failed"
            state["apply_error"] = error_message
            self._write_state(state)
            return state

        revision = int(bundle["protocol"]["revision"])
        if revision <= int(state.get("last_applied_revision", 0) or 0):
            state["last_sync_at"] = now_iso
            self._write_state(state)
            return state

        # 只有远端 revision 真正前进时才覆盖本地文件，避免重复写盘。
        self._apply_bundle_to_files(bundle, normalized_settings)
        state.update(
            {
                "last_applied_revision": revision,
                "last_sync_at": now_iso,
                "apply_status": "ok",
                "apply_error": "",
                "protocol": bundle["protocol"],
                "control": bundle["control"],
            }
        )
        self._write_state(state)
        return state

    def _apply_bundle_to_files(self, bundle: Dict[str, Any], normalized_settings: Dict[str, Any]) -> None:
        revision = bundle["protocol"]["revision"]
        backup_dir = os.path.join(runtime_paths.get_runtime_backup_dir(), f"remote_config_revision_{revision}")
        os.makedirs(backup_dir, exist_ok=True)

        raw_settings = self._load_raw_settings()
        merged_settings = dict(raw_settings)
        merged_settings.update(bundle["settings_config"])
        # 远端配置只接管业务配置，不覆盖本机 Supabase 凭据与设备标识。
        merged_settings["remote_control"] = raw_settings.get("remote_control", normalized_settings.get("remote_control", {}))

        self._backup_file(self.config_service.settings_path, backup_dir)
        self._backup_file(self.config_service.base_config_path, backup_dir)
        _atomic_write_json(self.config_service.settings_path, merged_settings)
        _atomic_write_json(self.config_service.base_config_path, bundle["config_json"])

        for package_name, app_config in bundle.get("app_configs", {}).items():
            target_path = os.path.join(self.config_service.data_root, f"{package_name}_config.json")
            self._backup_file(target_path, backup_dir)
            _atomic_write_json(target_path, app_config)

    def _backup_file(self, source_path: str, backup_dir: str) -> None:
        if not os.path.exists(source_path):
            return
        file_name = os.path.basename(source_path)
        backup_path = os.path.join(backup_dir, file_name)
        with open(source_path, "rb") as source_file:
            content = source_file.read()
        with open(backup_path, "wb") as backup_file:
            backup_file.write(content)

    def _collect_status_snapshot(
        self,
        settings: Dict[str, Any],
        state: Dict[str, Any],
        active_monitor_devices: List[str],
        network_ok: bool,
    ) -> Dict[str, Any]:
        remote_settings = settings.get("remote_control", {})
        adb_path = settings["adb_path"]
        try:
            connected_devices = adb_util.get_devices(adb_path)
        except Exception:
            connected_devices = []
            network_ok = False

        phones = []
        for device_serial in connected_devices:
            battery = adb_util.get_device_battery_info(adb_path, device_serial)
            phones.append(
                {
                    "serial": device_serial,
                    "connected": True,
                    "battery_percent": battery.get("level", -1),
                    "charging": bool(battery.get("charging", False)),
                    "battery_status": battery.get("status", "unknown"),
                    "screen_on": adb_util.is_device_screen_on(adb_path, device_serial),
                    "current_app": adb_util.get_foreground_app(adb_path, device_serial),
                    "last_seen_at": _utc_now_iso(),
                }
            )

        # 状态快照既会上报到服务端，也会落到本地，便于离线排查最近一次采样结果。
        return {
            "device_id": remote_settings.get("device_id") or socket.gethostname(),
            "device_name": remote_settings.get("device_name") or socket.gethostname(),
            "status_time": _utc_now_iso(),
            "app_version": __version__,
            "config_revision_applied": int(state.get("last_applied_revision", 0) or 0),
            "monitor_state": self.get_monitor_state(),
            "screenwatcher_state": "healthy" if network_ok else "degraded",
            "phones": phones,
            "network_ok": network_ok,
            "extra": {
                "active_monitor_devices": active_monitor_devices,
                "connected_device_count": len(connected_devices),
            },
        }

    def _build_device_payload(
        self,
        status_snapshot: Dict[str, Any],
        state: Dict[str, Any],
        remote_settings: Dict[str, Any],
    ) -> Dict[str, Any]:
        return {
            "device_id": remote_settings.get("device_id") or status_snapshot["device_id"],
            "device_name": remote_settings.get("device_name") or status_snapshot["device_name"],
            "app_version": status_snapshot["app_version"],
            "config_revision_applied": status_snapshot["config_revision_applied"],
            "config_apply_status": state.get("apply_status", "never"),
            "config_apply_error": state.get("apply_error", ""),
            "monitor_state": status_snapshot["monitor_state"],
            "last_seen_at": status_snapshot["status_time"],
            "updated_at": status_snapshot["status_time"],
        }