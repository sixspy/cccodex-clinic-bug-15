from __future__ import annotations

from app.db import get_db


def write_event(
    action: str,
    entity_type: str,
    entity_id: int = 0,
    detail: str = "",
    actor: str = "admin",
    db_path: str | None = None,
) -> dict:
    with get_db(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO audit_events(actor, action, entity_type, entity_id, detail)
            VALUES (?, ?, ?, ?, ?)
            """,
            (actor or "admin", action, entity_type, int(entity_id or 0), detail or ""),
        )
        eid = cur.lastrowid
        row = conn.execute("SELECT * FROM audit_events WHERE id=?", (eid,)).fetchone()
        return dict(row)


def list_events(limit: int = 100, db_path: str | None = None) -> list[dict]:
    limit = max(1, min(500, int(limit or 100)))
    with get_db(db_path) as conn:
        rows = conn.execute(
            """
            SELECT * FROM audit_events
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def summary(db_path: str | None = None) -> dict:
    with get_db(db_path) as conn:
        total = conn.execute("SELECT COUNT(*) AS c FROM audit_events").fetchone()["c"]
        by_action = conn.execute(
            """
            SELECT action, COUNT(*) AS c
            FROM audit_events
            GROUP BY action
            ORDER BY c DESC
            LIMIT 12
            """
        ).fetchall()
        recent = conn.execute(
            """
            SELECT action, entity_type, detail, created_at
            FROM audit_events
            ORDER BY id DESC
            LIMIT 5
            """
        ).fetchall()
        return {
            "total": total,
            "by_action": [dict(r) for r in by_action],
            "recent": [dict(r) for r in recent],
        }


def purge_old(keep_days: int = 30, db_path: str | None = None) -> dict:
    keep_days = max(1, int(keep_days or 30))
    with get_db(db_path) as conn:
        before = conn.execute("SELECT COUNT(*) AS c FROM audit_events").fetchone()["c"]
        conn.execute(
            """
            DELETE FROM audit_events
            WHERE created_at < datetime('now', ?)
            """,
            (f"-{keep_days} days",),
        )
        after = conn.execute("SELECT COUNT(*) AS c FROM audit_events").fetchone()["c"]
        removed = before - after
    write_event(
        "清理审计",
        "audit",
        0,
        f"保留{keep_days}天，删除{removed}条",
        db_path=db_path,
    )
    return {"removed": removed, "keep_days": keep_days, "remaining": after}
