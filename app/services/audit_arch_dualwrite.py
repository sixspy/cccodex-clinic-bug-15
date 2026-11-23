"""审计归档双写两轨（乙路）——本场禁双开。

本场只办甲路（旁路账册 cutover_book）。乙路写入口一律 409 拒绝，
且不得写入任何 meta；读接口纯读，绝不点灯、不留痕。
"""
from __future__ import annotations

from app.services.audit_arch import (
    _BAD,
    _OK,
    _TITLE,
    active_read_ref,
    archive_rows,
    dashboard,
    live_flag,
    truth_flag,
)
from app.services.errors import ServiceError

_SLUG = "audit_arch"


def dual_chip(db_path: str | None = None) -> str:
    # 纯读：没有独立芯片键时如实回显主钉定面徽标
    return dashboard(db_path)["chip"]


def seed_dual(db_path: str | None = None) -> None:
    """禁双开：乙路不允许预置任何状态，保留函数名仅为空操作。"""
    return None


def apply_dualwrite(note: str = "", db_path: str | None = None) -> dict:
    raise ServiceError(
        f"{_TITLE}本场只走甲路切流账册，乙路双写禁双开", 409
    )


def dual_board(db_path: str | None = None) -> dict:
    snap = dashboard(db_path)
    return {
        "dual_chip": snap["chip"],
        "truth": truth_flag(db_path),
        "active_read": active_read_ref(db_path),
        "archive": archive_rows(db_path),
        "live_flag": live_flag(db_path),
        "dash": snap,
        "fate": "disabled_dualwrite",
        "panel_pack_mismatch": snap["panel_pack_mismatch"],
        "title": f"{_TITLE}双写面（已禁双开）",
    }


def half_dual(db_path: str | None = None) -> dict:
    """纯读半面：不再点灯，只回显当前真实状态。"""
    return {
        "dual_chip": dashboard(db_path)["chip"],
        "truth": truth_flag(db_path),
        "active_read": active_read_ref(db_path),
    }
