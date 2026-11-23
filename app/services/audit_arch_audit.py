"""审计归档读轨审计（纯读）：汇总旁路账册与双写面，不产生任何写入。"""
from __future__ import annotations

from app.db import get_db
from app.services.audit_arch_cutover import board as cutover_board
from app.services.audit_arch_dualwrite import dual_board, half_dual


def audit_list(db_path: str | None = None) -> list[dict]:
    with get_db(db_path) as conn:
        rows = conn.execute(
            "SELECT key, value FROM meta WHERE key LIKE ? ORDER BY key",
            ("audit_arch_evt_%",),
        ).fetchall()
        return [{"key": r["key"], "value": r["value"]} for r in rows]


def audit_summary(db_path: str | None = None) -> dict:
    return {
        "title": "审计归档审计",
        "events": audit_list(db_path),
        "cutover": cutover_board(db_path),
        "dualwrite": dual_board(db_path),
        "half": half_dual(db_path),
    }
