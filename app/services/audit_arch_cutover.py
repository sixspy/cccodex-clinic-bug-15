"""审计归档切流账册（甲路，唯一收口路径）。

收口动作：
- 当刻活审计事件逐行封进只追加旁路账册（audit_arch_book_*）；
- 锁定全量指纹、置 reject_refresh=1、读轨分叉到 cutover_book；
- 收口后账册拒绝回刷：新增活审计事件不会改动账册与指纹；
- 缺锁争用由 audit_arch_sealed 唯一键兜底，并发只允许一份成功。
"""
from __future__ import annotations

from app.services.audit_arch import (
    _OK,
    _TITLE,
    active_read_ref,
    book_rows,
    commit_action,
    cutover_fp,
    dashboard,
    is_sealed,
    panel_chip,
    reject_refresh,
    truth_flag,
)
from app.services.errors import ServiceError

_SLUG = "audit_arch"


def book_events(db_path: str | None = None) -> list[dict]:
    """旁路账册只读视图。"""
    return book_rows(db_path)


def append_cutover(ref_id: int, note: str, db_path: str | None = None) -> dict:
    """甲路收口入口：委托 commit_action 在单事务内完成全部落地。"""
    result = commit_action(
        {"ref_id": int(ref_id or 0), "note": note or _TITLE},
        db_path,
    )
    return {
        "ref_id": int(ref_id or 0),
        "note": note or _TITLE,
        "panel": panel_chip(db_path),
        "truth": truth_flag(db_path),
        "active_read": active_read_ref(db_path),
        "cutover_fp": cutover_fp(db_path),
        "reject_refresh": reject_refresh(db_path),
        "sealed": is_sealed(db_path),
        "book_count": len(book_events(db_path)),
        "result": result,
    }


def cutover_rows(db_path: str | None = None) -> list[dict]:
    """只读：返回账册条目，不产生任何写入。"""
    ref = active_read_ref(db_path)
    chip = panel_chip(db_path)
    return [
        {
            "key": e["key"],
            "value": e["payload"],
            "fp": e["fp"],
            "chip": chip,
            "active_read": ref,
        }
        for e in book_events(db_path)
    ]


def board(db_path: str | None = None) -> dict:
    dash = dashboard(db_path)
    dash["cutover"] = cutover_rows(db_path)
    dash["book"] = book_events(db_path)
    dash["fate"] = "cutover_book"
    dash["sealed"] = is_sealed(db_path)
    return dash


def ensure_cutover_or_raise(db_path: str | None = None) -> None:
    if not is_sealed(db_path) or active_read_ref(db_path) != "cutover_book":
        raise ServiceError(f"{_TITLE}尚未按甲路收口，读轨仍在旧档", 409)
