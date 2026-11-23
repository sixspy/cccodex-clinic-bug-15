from __future__ import annotations

import json

from app.db import get_db
from app.services import audit as audit_svc
from app.services.errors import ServiceError

VALID_STATUS = ("草稿", "生效", "废止")
DEFAULT_FIELDS = ["subject_key", "visit_code", "visit_date", "investigator"]
DEFAULT_VISITS = ["V1", "V2", "V3", "EOT"]


def _parse_json_list(raw: str | list | None, fallback: list[str]) -> list[str]:
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip()]
    text = (raw or "").strip()
    if not text:
        return list(fallback)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ServiceError(f"JSON 字段无效: {exc}") from exc
    if not isinstance(data, list):
        raise ServiceError("字段列表必须是数组")
    return [str(x).strip() for x in data if str(x).strip()]


def list_protocols(db_path: str | None = None, status: str | None = None) -> list[dict]:
    with get_db(db_path) as conn:
        if status:
            if status not in VALID_STATUS:
                raise ServiceError("方案状态无效")
            rows = conn.execute(
                "SELECT * FROM protocols WHERE status=? ORDER BY id",
                (status,),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM protocols ORDER BY id").fetchall()
        items = []
        for r in rows:
            item = dict(r)
            item["required_fields_list"] = _parse_json_list(
                item.get("required_fields"), DEFAULT_FIELDS
            )
            item["visit_codes_list"] = _parse_json_list(
                item.get("visit_codes"), DEFAULT_VISITS
            )
            items.append(item)
        return items


def get_protocol(protocol_id: int, db_path: str | None = None) -> dict:
    with get_db(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM protocols WHERE id=?", (protocol_id,)
        ).fetchone()
        if not row:
            raise ServiceError("方案版本不存在", 404)
        item = dict(row)
        item["required_fields_list"] = _parse_json_list(
            item.get("required_fields"), DEFAULT_FIELDS
        )
        item["visit_codes_list"] = _parse_json_list(
            item.get("visit_codes"), DEFAULT_VISITS
        )
        used = conn.execute(
            "SELECT COUNT(*) AS c FROM visit_batches WHERE protocol_id=?",
            (protocol_id,),
        ).fetchone()["c"]
        item["batch_count"] = used
        return item


def create_protocol(
    title: str,
    version: str = "1.0",
    required_fields: list[str] | str | None = None,
    visit_codes: list[str] | str | None = None,
    note: str = "",
    db_path: str | None = None,
) -> dict:
    title = (title or "").strip()
    version = (version or "").strip()
    if not title:
        raise ServiceError("方案标题不能空")
    if not version:
        raise ServiceError("方案版本号不能空")
    fields = _parse_json_list(required_fields, DEFAULT_FIELDS)
    visits = _parse_json_list(visit_codes, DEFAULT_VISITS)
    if not fields:
        raise ServiceError("必填字段不能空")
    if not visits:
        raise ServiceError("访视编码不能空")
    with get_db(db_path) as conn:
        n = conn.execute("SELECT COUNT(*) AS c FROM protocols").fetchone()["c"] + 1
        code = f"PROT-{n:03d}"
        cur = conn.execute(
            """
            INSERT INTO protocols(
              protocol_code, version, title, status, required_fields, visit_codes, note
            ) VALUES (?, ?, ?, '草稿', ?, ?, ?)
            """,
            (
                code,
                version,
                title,
                json.dumps(fields, ensure_ascii=False),
                json.dumps(visits, ensure_ascii=False),
                (note or "").strip()[:200],
            ),
        )
        pid = cur.lastrowid
    audit_svc.write_event("创建方案版本", "protocol", pid, f"{title}@{version}", db_path=db_path)
    return get_protocol(pid, db_path)


def set_status(protocol_id: int, status: str, db_path: str | None = None) -> dict:
    if status not in VALID_STATUS:
        raise ServiceError("方案状态无效")
    with get_db(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM protocols WHERE id=?", (protocol_id,)
        ).fetchone()
        if not row:
            raise ServiceError("方案版本不存在", 404)
        if status == "生效":
            conn.execute(
                "UPDATE protocols SET status='废止' WHERE status='生效' AND id!=?",
                (protocol_id,),
            )
        conn.execute(
            "UPDATE protocols SET status=? WHERE id=?", (status, protocol_id)
        )
    audit_svc.write_event(
        "改方案状态", "protocol", protocol_id, status, db_path=db_path
    )
    return get_protocol(protocol_id, db_path)


def update_fields(
    protocol_id: int,
    required_fields: list[str] | str | None = None,
    visit_codes: list[str] | str | None = None,
    note: str | None = None,
    db_path: str | None = None,
) -> dict:
    with get_db(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM protocols WHERE id=?", (protocol_id,)
        ).fetchone()
        if not row:
            raise ServiceError("方案版本不存在", 404)
        if row["status"] == "废止":
            raise ServiceError("已废止方案不能改字段")
        fields = _parse_json_list(
            required_fields if required_fields is not None else row["required_fields"],
            DEFAULT_FIELDS,
        )
        visits = _parse_json_list(
            visit_codes if visit_codes is not None else row["visit_codes"],
            DEFAULT_VISITS,
        )
        new_note = row["note"] if note is None else (note or "").strip()[:200]
        conn.execute(
            """
            UPDATE protocols
            SET required_fields=?, visit_codes=?, note=?
            WHERE id=?
            """,
            (
                json.dumps(fields, ensure_ascii=False),
                json.dumps(visits, ensure_ascii=False),
                new_note,
                protocol_id,
            ),
        )
    audit_svc.write_event(
        "改方案字段", "protocol", protocol_id, ",".join(fields), db_path=db_path
    )
    return get_protocol(protocol_id, db_path)


def active_protocol(db_path: str | None = None) -> dict | None:
    items = list_protocols(db_path=db_path, status="生效")
    return items[0] if items else None
