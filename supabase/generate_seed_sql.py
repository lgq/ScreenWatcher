import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from screenwatcher.remote_protocol import compute_bundle_hash


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _read_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)
    if not isinstance(data, dict):
        raise ValueError(f"JSON 结构非法: {path}")
    return data


def _load_app_configs(project_root: Path) -> Dict[str, Dict[str, Any]]:
    app_configs: Dict[str, Dict[str, Any]] = {}
    for config_path in sorted(project_root.glob("*_config.json")):
        if config_path.name in {"settings_config.json"}:
            continue
        package_name = config_path.stem.replace("_config", "").strip()
        if not package_name:
            continue
        app_configs[package_name] = _read_json(config_path)
    return app_configs


def build_bundle(project_root: Path, project_id: str, revision: int, author: str) -> Dict[str, Any]:
    settings = _read_json(project_root / "settings_config.json")
    base_config = _read_json(project_root / "config.json")
    settings_for_remote = dict(settings)
    settings_for_remote.pop("remote_control", None)

    bundle: Dict[str, Any] = {
        "protocol": {
            "schema_version": 1,
            "project_id": project_id,
            "revision": revision,
            "created_at": _utc_now_iso(),
            "author": author,
            "hash": "",
            "effective_mode": "immediate",
            "min_client_version": "1.0.6",
        },
        "control": {
            "enabled": True,
            "monitor_state": "running",
            "poll_interval_seconds": 10,
            "status_upload_interval_seconds": 10,
        },
        "settings_config": settings_for_remote,
        "config_json": base_config,
        "app_configs": _load_app_configs(project_root),
    }
    bundle["protocol"]["hash"] = compute_bundle_hash(bundle)
    return bundle


def _json_sql_literal(payload: Dict[str, Any]) -> str:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "$json$" + serialized + "$json$::jsonb"


def build_seed_sql(project_id: str, revision: int, author: str, bundle: Dict[str, Any]) -> str:
    config_hash = bundle["protocol"]["hash"]
    config_json_literal = _json_sql_literal(bundle)
    safe_note = f"Seed revision {revision} by {author}".replace("'", "''")
    safe_author = author.replace("'", "''")
    safe_project = project_id.replace("'", "''")
    safe_hash = config_hash.replace("'", "''")

    return f"""-- 自动生成：初始 active 配置
begin;

update public.watch_config_versions
set is_active = false
where project_id = '{safe_project}'
  and is_active = true;

insert into public.watch_config_versions (
    project_id,
    revision,
    config_json,
    config_hash,
    schema_version,
    author_user_id,
    author_name,
    publish_note,
    is_active
) values (
    '{safe_project}',
    {revision},
    {config_json_literal},
    '{safe_hash}',
    1,
    '{safe_author}',
    '{safe_author}',
    '{safe_note}',
    true
);

commit;
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate Supabase seed SQL for active ScreenWatcher config.")
    parser.add_argument("--project-id", default="screenwatcher-prod")
    parser.add_argument("--revision", type=int, required=True)
    parser.add_argument("--author", default="seed-script")
    parser.add_argument("--project-root", default=str(PROJECT_ROOT))
    parser.add_argument("--bundle-output", default=str(Path(__file__).resolve().parent / "seed_bundle.json"))
    parser.add_argument("--sql-output", default=str(Path(__file__).resolve().parent / "seed_active_config.sql"))
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    bundle = build_bundle(project_root, args.project_id, args.revision, args.author)
    sql_text = build_seed_sql(args.project_id, args.revision, args.author, bundle)

    bundle_output = Path(args.bundle_output)
    sql_output = Path(args.sql_output)
    bundle_output.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
    sql_output.write_text(sql_text, encoding="utf-8")

    print(f"Bundle written: {bundle_output}")
    print(f"SQL written: {sql_output}")
    print(f"Config hash: {bundle['protocol']['hash']}")


if __name__ == "__main__":
    main()