from __future__ import annotations

from app.db import get_db
from app.services import audit as audit_svc
from app.services.errors import ServiceError


def dashboard(db_path: str | None = None) -> dict:
    from app.services.audit_arch_audit import audit_summary as _audit_arch_audit
    with get_db(db_path) as conn:
        sites = conn.execute("SELECT COUNT(*) AS c FROM trial_sites").fetchone()["c"]
        sites_enabled = conn.execute(
            "SELECT COUNT(*) AS c FROM trial_sites WHERE status='启用'"
        ).fetchone()["c"]
        protocols = conn.execute("SELECT COUNT(*) AS c FROM protocols").fetchone()["c"]
        batches = conn.execute("SELECT COUNT(*) AS c FROM visit_batches").fetchone()["c"]
        rows = conn.execute("SELECT COUNT(*) AS c FROM visit_rows").fetchone()["c"]
        gaps = conn.execute(
            """
            SELECT COUNT(*) AS c FROM visit_rows
            WHERE quality!='合格' AND status IN ('待检','待补采')
            """
        ).fetchone()["c"]
        findings = conn.execute(
            "SELECT COUNT(*) AS c FROM qc_findings WHERE status='开放'"
        ).fetchone()["c"]
        jobs = conn.execute(
            """
            SELECT COUNT(*) AS c FROM backfill_jobs
            WHERE status IN ('排队','执行中')
            """
        ).fetchone()["c"]
        audits = conn.execute("SELECT COUNT(*) AS c FROM audit_events").fetchone()["c"]
        by_batch_status = conn.execute(
            """
            SELECT status, COUNT(*) AS c FROM visit_batches GROUP BY status
            """
        ).fetchall()
        return {
            "sites": sites,
            "sites_enabled": sites_enabled,
            "protocols": protocols,
            "batches": batches,
            "rows": rows,
            "gaps": gaps,
            "open_findings": findings,
            "pending_jobs": jobs,
            "audits": audits,
            "batch_status": {r["status"]: r["c"] for r in by_batch_status},
            "audit_arch_audit": _audit_arch_audit(db_path),
        }


def run_reconcile(db_path: str | None = None) -> dict:
    with get_db(db_path) as conn:
        gap_rows = conn.execute(
            """
            SELECT COUNT(*) AS c FROM visit_rows
            WHERE quality!='合格' AND status IN ('待检','待补采')
            """
        ).fetchone()["c"]
        open_findings = conn.execute(
            "SELECT COUNT(*) AS c FROM qc_findings WHERE status='开放'"
        ).fetchone()["c"]
        pending_jobs = conn.execute(
            """
            SELECT COUNT(*) AS c FROM backfill_jobs
            WHERE status IN ('排队','执行中')
            """
        ).fetchone()["c"]
        # rows needing backfill but without open finding
        orphan_gaps = conn.execute(
            """
            SELECT COUNT(*) AS c FROM visit_rows r
            WHERE r.quality!='合格' AND r.status IN ('待检','待补采')
              AND NOT EXISTS (
                SELECT 1 FROM qc_findings f
                WHERE f.row_id=r.id AND f.status='开放'
              )
            """
        ).fetchone()["c"]
        # open findings whose row already qualified
        stale_findings = conn.execute(
            """
            SELECT COUNT(*) AS c FROM qc_findings f
            JOIN visit_rows r ON r.id=f.row_id
            WHERE f.status='开放' AND r.quality='合格'
            """
        ).fetchone()["c"]
        # gap rows without pending job
        uncovered = conn.execute(
            """
            SELECT COUNT(*) AS c FROM visit_rows r
            WHERE r.quality!='合格' AND r.status='待补采'
              AND NOT EXISTS (
                SELECT 1 FROM backfill_jobs j
                WHERE j.row_id=r.id AND j.status IN ('排队','执行中','成功')
              )
            """
        ).fetchone()["c"]
        mismatch = orphan_gaps + stale_findings + uncovered
        summary = (
            f"缺口行{gap_rows} · 开放发现{open_findings} · 待执行补采{pending_jobs} · "
            f"无发现缺口{orphan_gaps} · 陈旧发现{stale_findings} · 未覆盖补采{uncovered}"
        )
        cur = conn.execute(
            """
            INSERT INTO reconcile_reports(
              summary, gap_rows, open_findings, pending_jobs, mismatch
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (summary, gap_rows, open_findings, pending_jobs, mismatch),
        )
        rid = cur.lastrowid
        report = conn.execute(
            "SELECT * FROM reconcile_reports WHERE id=?", (rid,)
        ).fetchone()
        detail = {
            "orphan_gaps": orphan_gaps,
            "stale_findings": stale_findings,
            "uncovered_backfill": uncovered,
            "gap_by_quality": [
                dict(r)
                for r in conn.execute(
                    """
                    SELECT quality, COUNT(*) AS c FROM visit_rows
                    WHERE quality!='合格' AND status IN ('待检','待补采')
                    GROUP BY quality
                    """
                ).fetchall()
            ],
            "jobs_by_status": [
                dict(r)
                for r in conn.execute(
                    """
                    SELECT status, COUNT(*) AS c FROM backfill_jobs
                    GROUP BY status
                    """
                ).fetchall()
            ],
        }
    audit_svc.write_event(
        "访视对账", "reconcile_report", rid, summary, db_path=db_path
    )
    data = dict(report)
    data["detail"] = detail
    return data


def list_reports(db_path: str | None = None, limit: int = 20) -> list[dict]:
    limit = max(1, min(100, int(limit or 20)))
    with get_db(db_path) as conn:
        rows = conn.execute(
            """
            SELECT * FROM reconcile_reports
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_report(report_id: int, db_path: str | None = None) -> dict:
    with get_db(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM reconcile_reports WHERE id=?", (report_id,)
        ).fetchone()
        if not row:
            raise ServiceError("对账报告不存在", 404)
        return dict(row)


def site_gap_matrix(db_path: str | None = None) -> list[dict]:
    with get_db(db_path) as conn:
        rows = conn.execute(
            """
            SELECT s.id, s.site_code, s.name, s.status,
              COUNT(DISTINCT b.id) AS batch_count,
              COUNT(r.id) AS row_count,
              SUM(CASE WHEN r.quality!='合格' AND r.status IN ('待检','待补采') THEN 1 ELSE 0 END) AS gap_count,
              SUM(CASE WHEN f.status='开放' THEN 1 ELSE 0 END) AS open_findings
            FROM trial_sites s
            LEFT JOIN visit_batches b ON b.site_id=s.id
            LEFT JOIN visit_rows r ON r.batch_id=b.id
            LEFT JOIN qc_findings f ON f.row_id=r.id
            GROUP BY s.id
            ORDER BY s.id
            """
        ).fetchall()
        return [dict(r) for r in rows]
