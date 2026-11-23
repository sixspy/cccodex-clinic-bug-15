from __future__ import annotations

from app.db import get_db
from app.services import audit as audit_svc
from app.services.audit_arch import require_gate_or_raise
from app.services.errors import ServiceError

VALID_STATUS = ("启用", "停用", "观察")


def list_sites(db_path: str | None = None, status: str | None = None) -> list[dict]:
    with get_db(db_path) as conn:
        if status:
            if status not in VALID_STATUS:
                raise ServiceError("试验中心状态无效")
            rows = conn.execute(
                """
                SELECT s.*,
                  (SELECT COUNT(*) FROM visit_batches b WHERE b.site_id=s.id) AS batch_count,
                  (SELECT COALESCE(SUM(b.gap_count),0) FROM visit_batches b WHERE b.site_id=s.id) AS gap_total
                FROM trial_sites s
                WHERE s.status=?
                ORDER BY s.id
                """,
                (status,),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT s.*,
                  (SELECT COUNT(*) FROM visit_batches b WHERE b.site_id=s.id) AS batch_count,
                  (SELECT COALESCE(SUM(b.gap_count),0) FROM visit_batches b WHERE b.site_id=s.id) AS gap_total
                FROM trial_sites s
                ORDER BY s.id
                """
            ).fetchall()
        return [dict(r) for r in rows]


def get_site(site_id: int, db_path: str | None = None) -> dict:
    with get_db(db_path) as conn:
        row = conn.execute("SELECT * FROM trial_sites WHERE id=?", (site_id,)).fetchone()
        if not row:
            raise ServiceError("试验中心不存在", 404)
        batches = conn.execute(
            """
            SELECT id, batch_code, status, item_count, gap_count, note, created_at
            FROM visit_batches
            WHERE site_id=?
            ORDER BY id DESC
            """,
            (site_id,),
        ).fetchall()
        open_gaps = conn.execute(
            """
            SELECT COUNT(*) AS c
            FROM visit_rows r
            JOIN visit_batches b ON b.id=r.batch_id
            WHERE b.site_id=? AND r.quality!='合格' AND r.status IN ('待检','待补采')
            """,
            (site_id,),
        ).fetchone()["c"]
        data = dict(row)
        data["batches"] = [dict(b) for b in batches]
        data["open_gaps"] = open_gaps
        return data


def create_site(
    name: str,
    quota: int = 50,
    region: str = "",
    principal: str = "",
    note: str = "",
    db_path: str | None = None,
) -> dict:
    name = (name or "").strip()
    if not name:
        raise ServiceError("试验中心名称不能空")
    if len(name) > 80:
        raise ServiceError("试验中心名称过长")
    quota = max(1, min(9999, int(quota or 50)))
    region = (region or "").strip()[:40]
    principal = (principal or "").strip()[:40]
    note = (note or "").strip()[:200]
    require_gate_or_raise(db_path)
    with get_db(db_path) as conn:
        exists = conn.execute(
            "SELECT id FROM trial_sites WHERE name=?", (name,)
        ).fetchone()
        if exists:
            raise ServiceError("试验中心名称已存在")
        n = conn.execute("SELECT COUNT(*) AS c FROM trial_sites").fetchone()["c"] + 1
        code = f"SITE-{n:03d}"
        cur = conn.execute(
            """
            INSERT INTO trial_sites(site_code, name, status, quota, region, principal, note)
            VALUES (?, ?, '启用', ?, ?, ?, ?)
            """,
            (code, name, quota, region, principal, note),
        )
        site_id = cur.lastrowid
    audit_svc.write_event("创建试验中心", "trial_site", site_id, name, db_path=db_path)
    return get_site(site_id, db_path)


def set_status(site_id: int, status: str, db_path: str | None = None) -> dict:
    if status not in VALID_STATUS:
        raise ServiceError("试验中心状态无效")
    require_gate_or_raise(db_path)
    with get_db(db_path) as conn:
        row = conn.execute("SELECT * FROM trial_sites WHERE id=?", (site_id,)).fetchone()
        if not row:
            raise ServiceError("试验中心不存在", 404)
        if row["status"] == status:
            return get_site(site_id, db_path)
        if status == "停用":
            active = conn.execute(
                """
                SELECT COUNT(*) AS c FROM visit_batches
                WHERE site_id=? AND status='采集中'
                """,
                (site_id,),
            ).fetchone()["c"]
            if active:
                raise ServiceError("仍有采集中批次，不能停用中心")
        conn.execute("UPDATE trial_sites SET status=? WHERE id=?", (status, site_id))
    audit_svc.write_event(
        "改中心状态", "trial_site", site_id, status, db_path=db_path
    )
    return get_site(site_id, db_path)


def update_quota(site_id: int, quota: int, db_path: str | None = None) -> dict:
    require_gate_or_raise(db_path)
    quota = max(1, min(9999, int(quota or 1)))
    with get_db(db_path) as conn:
        row = conn.execute("SELECT id FROM trial_sites WHERE id=?", (site_id,)).fetchone()
        if not row:
            raise ServiceError("试验中心不存在", 404)
        conn.execute("UPDATE trial_sites SET quota=? WHERE id=?", (quota, site_id))
    audit_svc.write_event(
        "改中心配额", "trial_site", site_id, str(quota), db_path=db_path
    )
    return get_site(site_id, db_path)


def update_note(
    site_id: int,
    note: str = "",
    principal: str = "",
    region: str = "",
    db_path: str | None = None,
) -> dict:
    require_gate_or_raise(db_path)
    with get_db(db_path) as conn:
        row = conn.execute("SELECT id FROM trial_sites WHERE id=?", (site_id,)).fetchone()
        if not row:
            raise ServiceError("试验中心不存在", 404)
        conn.execute(
            """
            UPDATE trial_sites
            SET note=?, principal=?, region=?
            WHERE id=?
            """,
            (
                (note or "").strip()[:200],
                (principal or "").strip()[:40],
                (region or "").strip()[:40],
                site_id,
            ),
        )
    audit_svc.write_event("改中心备注", "trial_site", site_id, note or "", db_path=db_path)
    return get_site(site_id, db_path)


def status_counts(db_path: str | None = None) -> dict:
    with get_db(db_path) as conn:
        rows = conn.execute(
            """
            SELECT status, COUNT(*) AS c
            FROM trial_sites
            GROUP BY status
            """
        ).fetchall()
        data = {s: 0 for s in VALID_STATUS}
        for r in rows:
            data[r["status"]] = r["c"]
        data["total"] = sum(data.values())
        return data
