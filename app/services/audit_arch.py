"""归档钉定：甲路（旁路账册 cutover_book）收口面。

修复点：
- 徽标必须如实：未收口即「活审计可改」，皮面半修与读接口不再点亮假绿；
- 收口把当刻审计写入只追加、不可回刷的旁路账册（meta 键 audit_arch_book_*），
  锁定指纹、置 reject_refresh=1，并把读轨分叉到 cutover_book；
- 提交与入库同一事务，失败回滚并抛出可识别错误；
- 收口键 audit_arch_sealed 承担持久锁：重复/并发收口只有一份成功；
- 闸口 gate_allows_pipeline 不再有旁路开关：未对齐一律挡住活审计改写。
"""
from __future__ import annotations

import hashlib
import json
import sqlite3

from app.db import get_db
from app.services.errors import ServiceError

_SLUG = "audit_arch"
_OK = "归档已亮"
_BAD = "活审计可改"
_TITLE = "审计归档"
_OLD = "old_track"
_CUTOVER = "cutover_book"
_LIVE = "live_flag"

_GATE_MESSAGE = "审计归档未对齐（归档徽标与归档键号不符），挡住活审计改写"


def _meta_get(conn, key: str, default: str = "") -> str:
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def _meta_set(conn, key: str, value: str) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
        (key, value),
    )


def panel_chip(db_path: str | None = None) -> str:
    with get_db(db_path) as conn:
        return _meta_get(conn, f"{_SLUG}_panel_chip", _BAD)


def truth_flag(db_path: str | None = None) -> str:
    with get_db(db_path) as conn:
        return _meta_get(conn, f"{_SLUG}_truth", _BAD)


def active_read_ref(db_path: str | None = None) -> str:
    with get_db(db_path) as conn:
        return _meta_get(conn, f"{_SLUG}_active_read", _OLD)


def cutover_fp(db_path: str | None = None) -> str:
    with get_db(db_path) as conn:
        return _meta_get(conn, f"{_SLUG}_cutover_fp", "")


def reject_refresh(db_path: str | None = None) -> bool:
    with get_db(db_path) as conn:
        return _meta_get(conn, f"{_SLUG}_reject_refresh", "0") == "1"


def live_flag(db_path: str | None = None) -> str:
    with get_db(db_path) as conn:
        return _meta_get(conn, f"{_SLUG}_live_flag", "")


def is_sealed(db_path: str | None = None) -> bool:
    with get_db(db_path) as conn:
        return _meta_get(conn, f"{_SLUG}_sealed", "0") == "1"


def archive_rows(db_path: str | None = None) -> list[dict]:
    with get_db(db_path) as conn:
        rows = conn.execute(
            "SELECT key, value FROM meta WHERE key LIKE ? ORDER BY key",
            (f"{_SLUG}_archive_%",),
        ).fetchall()
        return [{"key": r["key"], "value": r["value"]} for r in rows]


def pack_rows(db_path: str | None = None) -> list[dict]:
    with get_db(db_path) as conn:
        rows = conn.execute(
            "SELECT key, value FROM meta WHERE key LIKE ? ORDER BY key",
            (f"{_SLUG}_pack_%",),
        ).fetchall()
        return [{"key": r["key"], "value": r["value"]} for r in rows]


def book_rows(db_path: str | None = None) -> list[dict]:
    """旁路账册只读视图：按账册序号返回收口当刻封存的审计事件。"""
    with get_db(db_path) as conn:
        rows = conn.execute(
            "SELECT key, value FROM meta WHERE key LIKE ? ORDER BY key",
            (f"{_SLUG}_book_%",),
        ).fetchall()
        items = []
        for r in rows:
            try:
                payload = json.loads(r["value"])
            except (TypeError, json.JSONDecodeError):
                continue
            items.append({"key": r["key"], **payload})
        return items


def seed_skew(db_path: str | None = None) -> None:
    """初始/测试骨架：徽标如实显示未收口，无旁路开关。"""
    with get_db(db_path) as conn:
        _meta_set(conn, f"{_SLUG}_panel_chip", _BAD)
        _meta_set(conn, f"{_SLUG}_truth", _BAD)
        _meta_set(conn, f"{_SLUG}_counter", "0")
        _meta_set(conn, f"{_SLUG}_gate_bypass", "0")
        _meta_set(conn, f"{_SLUG}_active_read", _OLD)
        _meta_set(conn, f"{_SLUG}_cutover_fp", "")
        _meta_set(conn, f"{_SLUG}_reject_refresh", "0")
        _meta_set(conn, f"{_SLUG}_live_flag", "")
        _meta_set(conn, f"{_SLUG}_mode", "")
        # 收口锁键在未收口时必须不存在：commit 用唯一 INSERT 抢锁，
        # 并发/重复收口时数据库直接 IntegrityError，只有一份成功。
        conn.execute("DELETE FROM meta WHERE key=?", (f"{_SLUG}_sealed",))
        _meta_set(conn, f"{_SLUG}_old_track", "pending|stale")
        _meta_set(conn, f"{_SLUG}_pack_decoy", "stale-fp|pending")


def paint_ok(db_path: str | None = None) -> str:
    """皮面点灯（半修演示用）：只改展示键，绝不碰读轨与收口状态。"""
    with get_db(db_path) as conn:
        _meta_set(conn, f"{_SLUG}_panel_chip", _OK)
        _meta_set(conn, f"{_SLUG}_display_only", "1")
    return _OK


def commit_action(payload: dict | None = None, db_path: str | None = None) -> dict:
    """甲路收口：同一事务内完成账册封存、指纹锁定、读轨分叉。

    - 重复/并发收口由 audit_arch_sealed 持久锁挡住，只允许一份成功；
    - 任何一步失败整体回滚，并抛出带「入库失败」的 ServiceError；
    - 提交成功即刻提交入库（get_db 退出即 commit）。
    """
    payload = payload or {}
    try:
        with get_db(db_path) as conn:
            # 持久锁：唯一键 INSERT，重复/并发收口在这里被数据库挡下
            try:
                conn.execute(
                    "INSERT INTO meta(key, value) VALUES (?, ?)",
                    (f"{_SLUG}_sealed", "1"),
                )
            except sqlite3.IntegrityError as exc:
                raise ServiceError(
                    f"{_TITLE}已收口，禁止重复收口", 409
                ) from exc

            events = [
                dict(r)
                for r in conn.execute(
                    """
                    SELECT id, actor, action, entity_type, entity_id, detail, created_at
                    FROM audit_events ORDER BY id
                    """
                ).fetchall()
            ]

            # 1) 旁路账册：逐行只追加封存
            digest = hashlib.sha256()
            for ev in events:
                line = json.dumps(ev, ensure_ascii=False, sort_keys=True)
                digest.update(line.encode("utf-8"))
                fp = hashlib.sha256(line.encode("utf-8")).hexdigest()[:16]
                _meta_set(
                    conn,
                    f"{_SLUG}_book_{ev['id']:08d}",
                    json.dumps(
                        {"payload": ev, "fp": fp, "sealed_at": ev["created_at"]},
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                )
            fp_value = digest.hexdigest()

            # 2) 锁指纹、拒回刷、读轨分叉到旁路账册
            c = int(_meta_get(conn, f"{_SLUG}_counter", "0") or "0") + 1
            _meta_set(conn, f"{_SLUG}_counter", str(c))
            _meta_set(conn, f"{_SLUG}_mode", _CUTOVER)
            _meta_set(conn, f"{_SLUG}_cutover_fp", fp_value)
            _meta_set(conn, f"{_SLUG}_reject_refresh", "1")
            _meta_set(conn, f"{_SLUG}_active_read", _CUTOVER)
            _meta_set(conn, f"{_SLUG}_truth", _OK)
            _meta_set(conn, f"{_SLUG}_panel_chip", _OK)
            _meta_set(conn, f"{_SLUG}_gate_bypass", "0")
            _meta_set(conn, f"{_SLUG}_last_payload", str(payload)[:200])
            _meta_set(conn, f"{_SLUG}_evt_{c}", f"cutover-seal fp={fp_value[:16]}")
            # 3) 清掉旧假绿残留，避免 stale-fp 软笔记继续误导
            _meta_set(conn, f"{_SLUG}_pack_decoy", "")
    except ServiceError:
        raise
    except Exception as exc:  # noqa: BLE001 — 入库失败必须报清楚
        raise ServiceError(f"{_TITLE}入库失败，已全部回滚: {exc}", 500) from exc

    return {
        "ok": True,
        "chip": _OK,
        "title": _TITLE,
        "counter": c,
        "active_read": active_read_ref(db_path),
        "cutover_fp": cutover_fp(db_path),
        "reject_refresh": reject_refresh(db_path),
        "archive_count": len(book_rows(db_path)),
        "live_flag": live_flag(db_path),
        "sealed": True,
        "message": f"{_TITLE}已收口并即刻入库",
    }


def half_fix_display(db_path: str | None = None) -> dict:
    """只修皮面：徽标亮，读轨仍旧轨——用于演示假绿被闸拦截。

    已按甲路收口后禁止半修：不得把读轨拨回旧档破坏收口。
    """
    if is_sealed(db_path):
        raise ServiceError(f"{_TITLE}已收口，禁止再做皮面半修", 409)
    paint_ok(db_path)
    with get_db(db_path) as conn:
        _meta_set(conn, f"{_SLUG}_truth", _BAD)
        _meta_set(conn, f"{_SLUG}_active_read", _OLD)
    return {
        "panel_chip": panel_chip(db_path),
        "truth": truth_flag(db_path),
        "active_read": active_read_ref(db_path),
        "archive_count": len(book_rows(db_path)),
        "half_fixed": True,
    }


def snapshot(db_path: str | None = None) -> dict:
    """纯读：绝不重置任何状态。"""
    with get_db(db_path) as conn:
        chip = _meta_get(conn, f"{_SLUG}_panel_chip", _BAD)
        truth = _meta_get(conn, f"{_SLUG}_truth", _BAD)
        ref = _meta_get(conn, f"{_SLUG}_active_read", _OLD)
        fp = _meta_get(conn, f"{_SLUG}_cutover_fp", "")
        reject = _meta_get(conn, f"{_SLUG}_reject_refresh", "0") == "1"
        live = _meta_get(conn, f"{_SLUG}_live_flag", "")
        sealed = _meta_get(conn, f"{_SLUG}_sealed", "0") == "1"
        pack_n = conn.execute(
            "SELECT COUNT(*) AS c FROM meta WHERE key LIKE ?",
            (f"{_SLUG}_pack_%",),
        ).fetchone()["c"]
        book_n = conn.execute(
            "SELECT COUNT(*) AS c FROM meta WHERE key LIKE ?",
            (f"{_SLUG}_book_%",),
        ).fetchone()["c"]
    aligned = (
        chip == truth == _OK
        and ref in (_CUTOVER, _LIVE)
        and (
            (ref == _CUTOVER and reject and sealed and fp not in ("", "stale-fp"))
            or (ref == _LIVE and live and book_n > 0)
        )
    )
    return {
        "title": _TITLE,
        "panel_chip": chip,
        "truth": truth,
        "pack_count": pack_n,
        "active_read": ref,
        "cutover_fp": fp,
        "reject_refresh": reject,
        "archive_count": book_n,
        "live_flag": live,
        "sealed": sealed,
        "aligned": aligned,
        "gate_bypass": False,
        "durable_count": book_n,
    }


def gate_allows_pipeline(db_path: str | None = None) -> bool:
    """业务闸语义：
    - 未收口且徽标如实（活审计可改）：放行待检池；
    - 收口对齐（徽标=已亮，读轨=旁路账册）：放行；
    - 徽标亮但键号仍旧轨（假绿）：一律挡住。
    """
    snap = snapshot(db_path)
    if snap["aligned"]:
        return True
    return snap["panel_chip"] != _OK


def require_gate_or_raise(db_path: str | None = None) -> None:
    """活审计改写入口统一闸口：徽标与键号对不上即 409 拦下。"""
    if not gate_allows_pipeline(db_path):
        raise ServiceError(_GATE_MESSAGE, 409)


def dashboard(db_path: str | None = None) -> dict:
    snap = snapshot(db_path)
    rows = pack_rows(db_path)
    durable = [r for r in rows if not str(r.get("key", "")).endswith("_decoy")]
    return {
        "title": _TITLE,
        "chip": snap["panel_chip"],
        "truth": snap["truth"],
        "pack_count": snap["pack_count"],
        "durable_count": len(durable),
        "rows": rows,
        "active_read": snap["active_read"],
        "cutover_fp": snap["cutover_fp"],
        "reject_refresh": snap["reject_refresh"],
        "archive_count": snap["archive_count"],
        "live_flag": snap["live_flag"],
        "sealed": snap["sealed"],
        "aligned": snap["aligned"],
        "panel_pack_mismatch": snap["panel_chip"] == _OK and not snap["aligned"],
        "ok_chip": _OK,
        "bad_chip": _BAD,
        "label": "归档钉定",
        "read_tracks": {
            "old_track": _OLD,
            "cutover_book": _CUTOVER,
            "live_flag": _LIVE,
        },
    }


def list_events(db_path: str | None = None) -> list[dict]:
    with get_db(db_path) as conn:
        rows = conn.execute(
            "SELECT key, value FROM meta WHERE key LIKE ? ORDER BY key",
            (f"{_SLUG}_evt_%",),
        ).fetchall()
        return [{"key": r["key"], "note": r["value"]} for r in rows]


def record_event(note: str, db_path: str | None = None) -> dict:
    """记笔记：不再顺手点亮徽标。"""
    with get_db(db_path) as conn:
        c = int(_meta_get(conn, f"{_SLUG}_counter", "0") or "0") + 1
        _meta_set(conn, f"{_SLUG}_counter", str(c))
        _meta_set(conn, f"{_SLUG}_evt_{c}", note or _BAD)
    return dashboard(db_path)


def reconcile_display(db_path: str | None = None) -> dict:
    return half_fix_display(db_path)


def require_pack_or_raise(db_path: str | None = None) -> None:
    snap = snapshot(db_path)
    if not snap["aligned"]:
        raise ServiceError(f"{_TITLE}读轨未对齐，禁止放行", 409)
