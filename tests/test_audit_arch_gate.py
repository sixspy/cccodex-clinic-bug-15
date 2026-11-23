"""审计归档假绿修复（clinic-bug-15）败测用例：先于改码落地。

覆盖：
- 初始徽标如实，业务链放行；
- 半修皮面制造假绿后，活审计改写全链路被闸拦下且库内无变化；
- 甲路切流账册收口：指纹/拒回刷/读轨分叉/账册不可变；
- 提交即入库、入库失败须报清楚且回滚；
- 重复与并发收口只有一份账册（缺锁争用回归）；
- 乙路双写禁双开；
- 读侧接口无副作用；
- 补采不再偷偷重刷假绿。
"""
from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.db import get_db
from app.services import (
    audit_arch,
    audit_arch_cutover,
    audit_arch_dualwrite,
    backfill,
    qc,
    reconcile,
    settings as settings_svc,
    visits,
)
from app.services.errors import ServiceError


def _meta_dump(db_path: str) -> dict[str, str]:
    with get_db(db_path) as conn:
        return {
            r["key"]: r["value"]
            for r in conn.execute("SELECT key, value FROM meta").fetchall()
        }


def _book_count(db_path: str) -> int:
    with get_db(db_path) as conn:
        return conn.execute(
            "SELECT COUNT(*) AS c FROM meta WHERE key LIKE 'audit_arch_book_%'"
        ).fetchone()["c"]


def _audit_count(db_path: str) -> int:
    with get_db(db_path) as conn:
        return conn.execute("SELECT COUNT(*) AS c FROM audit_events").fetchone()["c"]


# ---------- 1. 初始态：徽标如实，业务链放行 ----------

def test_initial_chip_is_truthful_and_pipeline_open(db_path):
    snap = audit_arch.snapshot(db_path)
    # 徽标不得在未收口时假亮
    assert snap["panel_chip"] == snap["truth"]
    assert snap["active_read"] == "old_track"
    assert snap["aligned"] is False
    assert audit_arch.gate_allows_pipeline(db_path) is True

    batches = visits.list_batches(db_path)
    batch = next(b for b in batches if b["status"] == "采集中")
    assert qc.scan_batch(batch["id"], db_path=db_path)["created"] >= 0
    detail = visits.get_batch(batch["id"], db_path)
    gap = next(
        r for r in detail["items"]
        if r["quality"] != "合格" and r["status"] in ("待检", "待补采")
    )
    job = backfill.enqueue_from_row(gap["id"], db_path=db_path)
    assert backfill.run_job(job["id"], succeed=True, db_path=db_path)["status"] == "成功"
    assert reconcile.run_reconcile(db_path)["id"] > 0
    assert settings_svc.update_setting("site_quota_warn", "41", db_path=db_path)


# ---------- 2. 假绿（皮面亮、读轨旧）必须挡住活审计改写 ----------

@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: qc.scan_batch(1, db_path=p),
        lambda p: qc.close_finding(1, db_path=p),
        lambda p: qc.reopen_finding(1, db_path=p),
        lambda p: backfill.enqueue_from_row(1, db_path=p),
        lambda p: backfill.run_job(1, succeed=True, db_path=p),
        lambda p: backfill.retry_job(1, db_path=p),
        lambda p: reconcile.run_reconcile(db_path=p),
        lambda p: settings_svc.update_setting("site_quota_warn", "42", db_path=p),
        lambda p: visits.mock_crawl(2, count=1, db_path=p),
        lambda p: visits.ingest_ok_rows(1, db_path=p),
    ],
)
def test_fake_green_chip_blocks_every_live_write(db_path, mutate):
    # 半修只亮皮面：徽标亮、读轨仍旧轨 => 假绿
    audit_arch.half_fix_display(db_path)
    snap = audit_arch.snapshot(db_path)
    assert snap["panel_chip"] == audit_arch._OK
    assert snap["active_read"] == "old_track"
    assert snap["aligned"] is False
    assert audit_arch.gate_allows_pipeline(db_path) is False

    before_findings = qc.summary(db_path)["open"]
    before_jobs = backfill.summary(db_path)["total"]
    before_reports = len(reconcile.list_reports(db_path))
    before_settings = settings_svc.get_setting("site_quota_warn", db_path)["value"]

    with pytest.raises(ServiceError) as exc:
        mutate(db_path)
    assert exc.value.status_code == 409
    assert "活审计改写" in exc.value.message

    # 库里业务数字一个都不许变
    assert qc.summary(db_path)["open"] == before_findings
    assert backfill.summary(db_path)["total"] == before_jobs
    assert len(reconcile.list_reports(db_path)) == before_reports
    assert settings_svc.get_setting("site_quota_warn", db_path)["value"] == before_settings


# ---------- 3. 甲路收口：旁路账册、指纹、拒回刷、读轨分叉 ----------

def test_cutover_commit_seals_book_and_switches_read_track(db_path):
    live_before = _audit_count(db_path)
    result = audit_arch.commit_action({"ref": 1}, db_path)

    assert result["ok"] is True
    snap = audit_arch.snapshot(db_path)
    assert snap["aligned"] is True
    assert snap["panel_chip"] == audit_arch._OK
    assert snap["truth"] == audit_arch._OK
    assert snap["active_read"] == "cutover_book"
    assert snap["reject_refresh"] is True
    assert snap["cutover_fp"] not in ("", "stale-fp")
    assert len(snap["cutover_fp"]) >= 16

    # 账册行数 == 收口当刻活审计表行数
    assert _book_count(db_path) == live_before
    book = audit_arch_cutover.book_events(db_path)
    assert len(book) == live_before
    assert all("payload" in e and e["fp"] for e in book)

    # 指纹对同内容稳定
    fp_first = audit_arch.cutover_fp(db_path)
    board = audit_arch_cutover.board(db_path)
    assert board["aligned"] is True
    assert board["active_read"] == "cutover_book"
    assert audit_arch.cutover_fp(db_path) == fp_first


def test_sealed_book_rejects_refresh_from_new_live_events(db_path):
    audit_arch.commit_action({}, db_path)
    sealed_book = audit_arch_cutover.book_events(db_path)
    sealed_fp = audit_arch.cutover_fp(db_path)

    # 收口后活轨仍可追加新审计，但旁路账册与指纹不得回刷
    from app.services import audit as audit_svc
    audit_svc.write_event("收口后新事件", "audit", 0, "不应进账册", db_path=db_path)

    assert audit_arch_cutover.book_events(db_path) == sealed_book
    assert audit_arch.cutover_fp(db_path) == sealed_fp
    assert audit_arch.reject_refresh(db_path) is True
    assert audit_arch.active_read_ref(db_path) == "cutover_book"


def test_gate_reopens_after_real_cutover(db_path):
    audit_arch.commit_action({}, db_path)
    assert audit_arch.gate_allows_pipeline(db_path) is True
    batches = visits.list_batches(db_path)
    batch = next(b for b in batches if b["status"] == "采集中")
    # 收口后业务写入恢复，且不再产生假绿
    assert qc.scan_batch(batch["id"], db_path=db_path)["created"] >= 0
    snap = audit_arch.snapshot(db_path)
    assert snap["aligned"] is True
    assert snap["panel_chip"] == snap["truth"] == audit_arch._OK


# ---------- 4. 提交即入库、失败报清楚且回滚 ----------

def test_commit_is_durable_immediately(db_path):
    audit_arch.commit_action({}, db_path)
    # 全新连接（模拟下次请求）必须看得到收口结果
    with sqlite3.connect(db_path) as raw:
        keys = {r[0]: r[1] for r in raw.execute("SELECT key, value FROM meta")}
    assert keys["audit_arch_active_read"] == "cutover_book"
    assert keys["audit_arch_reject_refresh"] == "1"
    assert keys["audit_arch_truth"] == audit_arch._OK
    assert keys["audit_arch_sealed"] == "1"
    assert keys["audit_arch_cutover_fp"] not in ("", "stale-fp")


def test_commit_failure_rolls_back_and_reports_clearly(db_path, monkeypatch):
    real_meta_set = audit_arch._meta_set

    def boom(conn, key, value):
        if key.startswith("audit_arch_book_"):
            raise RuntimeError("模拟磁盘入库失败")
        real_meta_set(conn, key, value)

    monkeypatch.setattr(audit_arch, "_meta_set", boom)
    with pytest.raises(ServiceError) as exc:
        audit_arch.commit_action({}, db_path)
    assert exc.value.status_code >= 500
    assert "入库失败" in exc.value.message

    # 全部回滚：未收口（锁键随事务回滚而消失）、账册空、指纹仍空
    snap = audit_arch.snapshot(db_path)
    assert snap["aligned"] is False
    assert snap["sealed"] is False
    assert _book_count(db_path) == 0
    assert audit_arch.cutover_fp(db_path) in ("", "stale-fp")


# ---------- 5. 重复与并发收口：缺锁争用回归 ----------

def test_double_commit_conflicts(db_path):
    audit_arch.commit_action({}, db_path)
    with pytest.raises(ServiceError) as exc:
        audit_arch.commit_action({}, db_path)
    assert exc.value.status_code == 409
    assert "已收口" in exc.value.message


def test_half_fix_refused_after_seal_and_state_untouched(db_path):
    audit_arch.commit_action({}, db_path)
    before = _meta_dump(db_path)
    with pytest.raises(ServiceError) as exc:
        audit_arch.half_fix_display(db_path)
    assert exc.value.status_code == 409
    # 收口状态一个键都不许被半修拨回旧轨
    assert _meta_dump(db_path) == before
    assert audit_arch.active_read_ref(db_path) == "cutover_book"
    assert audit_arch.snapshot(db_path)["aligned"] is True


def test_concurrent_commits_seal_exactly_one_book(db_path):
    outcomes: list[str] = []

    def worker() -> None:
        try:
            audit_arch.commit_action({"worker": True}, db_path)
            outcomes.append("ok")
        except ServiceError as exc:
            outcomes.append(f"err{exc.status_code}")

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: worker(), range(8)))

    assert outcomes.count("ok") == 1
    assert all(o == "err409" for o in outcomes if o != "ok")
    # 账册只允许一份：指纹键唯一、账册条目数等于活表一次快照
    assert _book_count(db_path) == _audit_count(db_path)
    snap = audit_arch.snapshot(db_path)
    assert snap["aligned"] is True


# ---------- 6. 乙路双写禁双开 ----------

def test_dualwrite_route_is_refused_and_leaves_no_trace(db_path):
    before = _meta_dump(db_path)
    with pytest.raises(ServiceError) as exc:
        audit_arch_dualwrite.apply_dualwrite("审计归档", db_path)
    assert exc.value.status_code == 409
    assert "禁双开" in exc.value.message

    after = _meta_dump(db_path)
    assert after == before
    snap = audit_arch.snapshot(db_path)
    assert snap["active_read"] != "live_flag"
    assert snap["live_flag"] == ""


# ---------- 7. 读侧接口不得有副作用 ----------

@pytest.mark.parametrize(
    "reader",
    [
        lambda p: audit_arch.snapshot(p),
        lambda p: audit_arch.dashboard(p),
        lambda p: audit_arch_cutover.board(p),
        lambda p: audit_arch_dualwrite.dual_board(p),
        lambda p: audit_arch_dualwrite.half_dual(p),
        lambda p: reconcile.dashboard(p),
    ],
)
def test_read_apis_have_no_side_effects(db_path, reader):
    before = _meta_dump(db_path)
    reader(db_path)
    reader(db_path)
    assert _meta_dump(db_path) == before


# ---------- 8. 补采链路不得再偷偷重刷假绿 ----------

def test_batch_backfill_does_not_touch_arch_state(db_path):
    before = _meta_dump(db_path)
    batches = visits.list_batches(db_path)
    batch = next(b for b in batches if b["status"] == "采集中")
    result = backfill.enqueue_gaps_for_batch(batch["id"], db_path)
    assert "enqueued" in result
    assert _meta_dump(db_path) == before


# ---------- 9. 列表/详情/队列形态都带归档状态 ----------

def test_board_shapes_carry_arch_status(db_path):
    dash = reconcile.dashboard(db_path)
    assert "audit_arch" in dash
    status = dash["audit_arch"]
    for key in ("chip", "truth", "aligned", "active_read", "sealed"):
        assert key in status

    board = audit_arch_cutover.board(db_path)
    for key in ("chip", "truth", "active_read", "aligned", "panel_pack_mismatch"):
        assert key in board
