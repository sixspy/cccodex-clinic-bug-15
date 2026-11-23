from __future__ import annotations

from app.db import get_db
from app.services import audit as audit_svc
from app.services.errors import ServiceError


def list_settings(db_path: str | None = None) -> list[dict]:
    with get_db(db_path) as conn:
        rows = conn.execute(
            "SELECT key, value, label FROM app_settings ORDER BY key"
        ).fetchall()
        return [dict(r) for r in rows]


def get_setting(key: str, db_path: str | None = None) -> dict:
    key = (key or "").strip()
    if not key:
        raise ServiceError("设置键不能空")
    with get_db(db_path) as conn:
        row = conn.execute(
            "SELECT key, value, label FROM app_settings WHERE key=?", (key,)
        ).fetchone()
        if not row:
            raise ServiceError("设置项不存在", 404)
        return dict(row)


def update_setting(key: str, value: str, db_path: str | None = None) -> dict:
    key = (key or "").strip()
    if not key:
        raise ServiceError("设置键不能空")
    value = "" if value is None else str(value).strip()
    if len(value) > 200:
        raise ServiceError("设置值过长")
    with get_db(db_path) as conn:
        row = conn.execute(
            "SELECT key, value, label FROM app_settings WHERE key=?", (key,)
        ).fetchone()
        if not row:
            raise ServiceError("设置项不存在", 404)
        if key in ("qc_auto_scan", "backfill_max_attempt", "site_quota_warn"):
            if not value.isdigit():
                raise ServiceError("该设置必须是数字")
            if key == "backfill_max_attempt" and int(value) < 1:
                raise ServiceError("补采最大次数至少为 1")
        conn.execute(
            "UPDATE app_settings SET value=? WHERE key=?", (value, key)
        )
    audit_svc.write_event("改台参数", "setting", 0, f"{key}={value}", db_path=db_path)
    return get_setting(key, db_path)


def get_int(key: str, default: int = 0, db_path: str | None = None) -> int:
    try:
        item = get_setting(key, db_path)
        return int(item["value"])
    except (ServiceError, ValueError, TypeError):
        return default


def bulk_snapshot(db_path: str | None = None) -> dict:
    items = list_settings(db_path)
    return {i["key"]: i["value"] for i in items}
