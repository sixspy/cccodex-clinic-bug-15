from __future__ import annotations

import json
from datetime import datetime

from app.db import get_db
from app.services import audit as audit_svc
from app.services import settings as settings_svc
from app.services.audit_arch import require_gate_or_raise
from app.services.errors import ServiceError

JOB_STATUS = ("排队", "执行中", "成功", "失败")


def list_jobs(
    db_path: str | None = None,
    status: str | None = None,
    row_id: int | None = None,
) -> list[dict]:
    clauses = []
    params: list = []
    if status:
        if status not in JOB_STATUS:
            raise ServiceError("补采任务状态无效")
        clauses.append("j.status=?")
        params.append(status)
    if row_id:
        clauses.append("j.row_id=?")
        params.append(int(row_id))
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    with get_db(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT j.*, r.subject_key, r.visit_code, r.quality, r.status AS row_status,
                   b.batch_code, s.name AS site_name
            FROM backfill_jobs j
            JOIN visit_rows r ON r.id=j.row_id
            JOIN visit_batches b ON b.id=r.batch_id
            JOIN trial_sites s ON s.id=b.site_id
            {where}
            ORDER BY j.id DESC
            LIMIT 500
            """,
            params,
        ).fetchall()
        return [dict(r) for r in rows]


def get_job(job_id: int, db_path: str | None = None) -> dict:
    with get_db(db_path) as conn:
        row = conn.execute(
            """
            SELECT j.*, r.subject_key, r.visit_code, r.payload, r.quality,
                   b.batch_code, s.name AS site_name
            FROM backfill_jobs j
            JOIN visit_rows r ON r.id=j.row_id
            JOIN visit_batches b ON b.id=r.batch_id
            JOIN trial_sites s ON s.id=b.site_id
            WHERE j.id=?
            """,
            (job_id,),
        ).fetchone()
        if not row:
            raise ServiceError("补采任务不存在", 404)
        return dict(row)


def enqueue_from_row(row_id: int, db_path: str | None = None) -> dict:
    row_id = int(row_id or 0)
    if row_id <= 0:
        raise ServiceError("必须指定访视行")
    require_gate_or_raise(db_path)
    with get_db(db_path) as conn:
        row = conn.execute("SELECT * FROM visit_rows WHERE id=?", (row_id,)).fetchone()
        if not row:
            raise ServiceError("访视行不存在", 404)
        batch = conn.execute(
            "SELECT * FROM visit_batches WHERE id=?", (row["batch_id"],)
        ).fetchone()
        if not batch or batch["status"] == "已关闭":
            raise ServiceError("已关闭批次不能排队补采")
        if row["quality"] == "合格" and row["status"] == "已入库":
            raise ServiceError("已入库合格行无需补采")
        pending = conn.execute(
            """
            SELECT id FROM backfill_jobs
            WHERE row_id=? AND status IN ('排队','执行中')
            """,
            (row_id,),
        ).fetchone()
        if pending:
            raise ServiceError("该行已有进行中的补采任务")
        n = conn.execute("SELECT COUNT(*) AS c FROM backfill_jobs").fetchone()["c"] + 1
        code = f"BF-{n:04d}"
        cur = conn.execute(
            """
            INSERT INTO backfill_jobs(job_code, row_id, status, attempt, message)
            VALUES (?, ?, '排队', 1, '等待执行')
            """,
            (code, row_id),
        )
        job_id = cur.lastrowid
        if row["status"] in ("待检", "已入库"):
            conn.execute(
                "UPDATE visit_rows SET status='待补采' WHERE id=?", (row_id,)
            )
    audit_svc.write_event(
        "排队补采", "backfill_job", job_id, f"row={row_id}", db_path=db_path
    )
    return get_job(job_id, db_path)


def enqueue_gaps_for_batch(batch_id: int, db_path: str | None = None) -> dict:
    require_gate_or_raise(db_path)
    with get_db(db_path) as conn:
        rows = conn.execute(
            """
            SELECT id FROM visit_rows
            WHERE batch_id=? AND quality!='合格' AND status IN ('待检','待补采')
            ORDER BY id
            """,
            (batch_id,),
        ).fetchall()
    jobs = []
    skipped = 0
    for r in rows:
        try:
            jobs.append(enqueue_from_row(r["id"], db_path=db_path))
        except ServiceError:
            skipped += 1
    audit_svc.write_event(
        "批量排队补采",
        "visit_batch",
        batch_id,
        f"成功{len(jobs)}跳过{skipped}",
        db_path=db_path,
    )
    return {"enqueued": len(jobs), "skipped": skipped, "jobs": jobs}


def run_job(job_id: int, succeed: bool = True, db_path: str | None = None) -> dict:
    require_gate_or_raise(db_path)
    max_attempt = settings_svc.get_int("backfill_max_attempt", 3, db_path=db_path)
    with get_db(db_path) as conn:
        job = conn.execute(
            "SELECT * FROM backfill_jobs WHERE id=?", (job_id,)
        ).fetchone()
        if not job:
            raise ServiceError("补采任务不存在", 404)
        if job["status"] in ("成功",):
            return get_job(job_id, db_path)
        if job["status"] == "执行中":
            raise ServiceError("任务正在执行中")
        if job["attempt"] > max_attempt:
            conn.execute(
                """
                UPDATE backfill_jobs
                SET status='失败', message=?, finished_at=datetime('now')
                WHERE id=?
                """,
                (f"超过最大尝试次数 {max_attempt}", job_id),
            )
            return get_job(job_id, db_path)
        now = datetime.now().isoformat(timespec="seconds")
        conn.execute(
            """
            UPDATE backfill_jobs
            SET status='执行中', started_at=?, message='补采执行中'
            WHERE id=?
            """,
            (now, job_id),
        )
        row = conn.execute(
            "SELECT * FROM visit_rows WHERE id=?", (job["row_id"],)
        ).fetchone()
        if not row:
            conn.execute(
                """
                UPDATE backfill_jobs
                SET status='失败', message='访视行已丢失', finished_at=datetime('now'),
                    attempt=attempt+1
                WHERE id=?
                """,
                (job_id,),
            )
            return get_job(job_id, db_path)
        if succeed:
            payload = row["payload"]
            try:
                data = json.loads(payload) if payload else {}
            except json.JSONDecodeError:
                data = {}
            if not isinstance(data, dict):
                data = {}
            data.setdefault("visit_date", datetime.now().strftime("%Y-%m-%d"))
            data.setdefault("investigator", "补采医生")
            data["backfilled"] = True
            data["backfill_job"] = job["job_code"]
            new_payload = json.dumps(data, ensure_ascii=False)
            conn.execute(
                """
                UPDATE visit_rows
                SET payload=?, quality='合格', status='已入库'
                WHERE id=?
                """,
                (new_payload, row["id"]),
            )
            conn.execute(
                """
                UPDATE qc_findings SET status='已关闭'
                WHERE row_id=? AND status='开放'
                """,
                (row["id"],),
            )
            conn.execute(
                """
                UPDATE backfill_jobs
                SET status='成功', message='补采成功并已入库',
                    finished_at=datetime('now'), attempt=attempt
                WHERE id=?
                """,
                (job_id,),
            )
            gap = conn.execute(
                """
                SELECT COUNT(*) AS c FROM visit_rows
                WHERE batch_id=? AND quality!='合格'
                """,
                (row["batch_id"],),
            ).fetchone()["c"]
            item_count = conn.execute(
                "SELECT COUNT(*) AS c FROM visit_rows WHERE batch_id=?",
                (row["batch_id"],),
            ).fetchone()["c"]
            conn.execute(
                "UPDATE visit_batches SET gap_count=?, item_count=? WHERE id=?",
                (gap, item_count, row["batch_id"]),
            )
        else:
            conn.execute(
                """
                UPDATE backfill_jobs
                SET status='失败', message='模拟补采失败',
                    finished_at=datetime('now'), attempt=attempt+1
                WHERE id=?
                """,
                (job_id,),
            )
    audit_svc.write_event(
        "执行补采",
        "backfill_job",
        job_id,
        "成功" if succeed else "失败",
        db_path=db_path,
    )
    return get_job(job_id, db_path)


def retry_job(job_id: int, db_path: str | None = None) -> dict:
    require_gate_or_raise(db_path)
    with get_db(db_path) as conn:
        job = conn.execute(
            "SELECT * FROM backfill_jobs WHERE id=?", (job_id,)
        ).fetchone()
        if not job:
            raise ServiceError("补采任务不存在", 404)
        if job["status"] not in ("失败",):
            raise ServiceError("只有失败任务可以重试")
        max_attempt = settings_svc.get_int("backfill_max_attempt", 3, db_path=db_path)
        if job["attempt"] >= max_attempt:
            raise ServiceError("已达最大尝试次数，不能重试")
        conn.execute(
            """
            UPDATE backfill_jobs
            SET status='排队', message='失败后重新排队',
                started_at=NULL, finished_at=NULL
            WHERE id=?
            """,
            (job_id,),
        )
    audit_svc.write_event("重试补采", "backfill_job", job_id, "", db_path=db_path)
    return get_job(job_id, db_path)


def summary(db_path: str | None = None) -> dict:
    with get_db(db_path) as conn:
        rows = conn.execute(
            """
            SELECT status, COUNT(*) AS c
            FROM backfill_jobs
            GROUP BY status
            """
        ).fetchall()
        data = {s: 0 for s in JOB_STATUS}
        for r in rows:
            data[r["status"]] = r["c"]
        data["total"] = sum(data.values())
        return data
