from __future__ import annotations

import json

from app.db import _meta_get, _meta_set, ensure_db, get_db


def seed_if_needed(db_path: str | None = None) -> None:
    ensure_db()
    with get_db(db_path) as conn:
        if _meta_get(conn, "seeded") == "1":
            return

        settings = [
            ("qc_auto_scan", "1", "缺口行自动质控扫描"),
            ("backfill_max_attempt", "3", "补采最大尝试次数"),
            ("site_quota_warn", "40", "中心配额告警阈值"),
            ("reconcile_label", "访视缺口对账口径A", "对账口径标签"),
            ("audit_keep_days", "45", "审计保留天数"),
            ("default_visit_codes", "V1,V2,V3,EOT", "默认访视编码清单"),
            ("crawl_page_size", "20", "模拟抓取每批条数"),
            ("clinic_timezone", "Asia/Shanghai", "台账时区"),
        ]
        conn.executemany(
            "INSERT OR IGNORE INTO app_settings(key, value, label) VALUES (?,?,?)",
            settings,
        )

        sites = [
            ("SITE-001", "华东协同中心", "启用", 80, "上海", "陈主任", "主采集中心"),
            ("SITE-002", "华北协作医院", "启用", 60, "北京", "刘主任", "次采集中心"),
            ("SITE-003", "西南观察点", "观察", 30, "成都", "周医生", "观察中的中心"),
            ("SITE-004", "华南暂停站", "停用", 20, "广州", "吴医生", "已停用示例"),
        ]
        site_ids = []
        for code, name, status, quota, region, principal, note in sites:
            cur = conn.execute(
                """
                INSERT INTO trial_sites(site_code, name, status, quota, region, principal, note)
                VALUES (?,?,?,?,?,?,?)
                """,
                (code, name, status, quota, region, principal, note),
            )
            site_ids.append(cur.lastrowid)

        protocols = [
            (
                "PROT-001",
                "1.0",
                "肿瘤随访方案甲",
                "生效",
                ["subject_key", "visit_code", "visit_date", "investigator", "weight_kg"],
                ["V1", "V2", "V3", "EOT"],
                "当前生效方案",
            ),
            (
                "PROT-002",
                "0.9",
                "肿瘤随访方案乙草稿",
                "草稿",
                ["subject_key", "visit_code", "visit_date", "investigator"],
                ["V1", "V2", "FU"],
                "草稿待审",
            ),
            (
                "PROT-003",
                "0.5",
                "旧版随访方案",
                "废止",
                ["subject_key", "visit_code", "visit_date"],
                ["V1", "V2"],
                "历史废止",
            ),
        ]
        protocol_ids = []
        for code, ver, title, status, fields, visits, note in protocols:
            cur = conn.execute(
                """
                INSERT INTO protocols(
                  protocol_code, version, title, status, required_fields, visit_codes, note
                ) VALUES (?,?,?,?,?,?,?)
                """,
                (
                    code,
                    ver,
                    title,
                    status,
                    json.dumps(fields, ensure_ascii=False),
                    json.dumps(visits, ensure_ascii=False),
                    note,
                ),
            )
            protocol_ids.append(cur.lastrowid)

        batches = [
            ("VB-SITE-001-SEED-01", site_ids[0], protocol_ids[0], "已收齐", "华东首轮访视抓取"),
            ("VB-SITE-002-SEED-01", site_ids[1], protocol_ids[0], "采集中", "华北进行中批次"),
            ("VB-SITE-003-SEED-01", site_ids[2], protocol_ids[0], "已关闭", "观察点历史批"),
            ("VB-SITE-001-SEED-02", site_ids[0], protocol_ids[0], "采集中", "华东第二批"),
        ]
        batch_ids = []
        for code, sid, pid, status, note in batches:
            cur = conn.execute(
                """
                INSERT INTO visit_batches(batch_code, site_id, protocol_id, status, note)
                VALUES (?,?,?,?,?)
                """,
                (code, sid, pid, status, note),
            )
            batch_ids.append(cur.lastrowid)

        rows = [
            (batch_ids[0], "S01-0001", "V1",
             json.dumps({"visit_date": "2026-11-01", "investigator": "王医生", "weight_kg": 62}, ensure_ascii=False),
             "合格", "已入库"),
            (batch_ids[0], "S01-0002", "V1",
             json.dumps({"visit_date": "", "investigator": "王医生", "weight_kg": 55}, ensure_ascii=False),
             "缺字段", "待补采"),
            (batch_ids[0], "S01-0003", "V2", "", "编码空", "待补采"),
            (batch_ids[0], "S01-0004", "V2",
             json.dumps({"visit_date": "2026-11-03", "investigator": "赵医生", "weight_kg": 70}, ensure_ascii=False),
             "合格", "已入库"),
            (batch_ids[0], "S01-0005", "V3",
             json.dumps({"visit_date": "2026-11-04", "investigator": "赵医生"}, ensure_ascii=False),
             "缺字段", "待检"),
            (batch_ids[1], "S02-0001", "V1",
             json.dumps({"visit_date": "2026-11-05", "investigator": "李医生", "weight_kg": 58}, ensure_ascii=False),
             "合格", "待检"),
            (batch_ids[1], "S02-0002", "V1",
             json.dumps({"visit_date": "2026-11-05", "investigator": "李医生", "weight_kg": 58}, ensure_ascii=False),
             "重复键", "待检"),
            (batch_ids[1], "S02-0003", "V2", "", "编码空", "待检"),
            (batch_ids[1], "S02-0004", "V2",
             json.dumps({"visit_date": "", "investigator": "", "weight_kg": 0}, ensure_ascii=False),
             "缺字段", "待补采"),
            (batch_ids[1], "S02-0005", "EOT",
             json.dumps({"visit_date": "2026-11-08", "investigator": "孙医生", "weight_kg": 64}, ensure_ascii=False),
             "合格", "待检"),
            (batch_ids[2], "S03-0001", "V1",
             json.dumps({"visit_date": "2026-10-01", "investigator": "周医生", "weight_kg": 60}, ensure_ascii=False),
             "合格", "已关闭"),
            (batch_ids[2], "S03-0002", "V2",
             json.dumps({"visit_date": "", "investigator": "周医生"}, ensure_ascii=False),
             "缺字段", "已关闭"),
            (batch_ids[3], "S01-0101", "V1",
             json.dumps({"visit_date": "2026-11-10", "investigator": "王医生", "weight_kg": 66}, ensure_ascii=False),
             "合格", "待检"),
            (batch_ids[3], "S01-0102", "V2", "", "编码空", "待检"),
            (batch_ids[3], "S01-0103", "V3",
             json.dumps({"visit_date": "2026-11-12", "investigator": "赵医生", "weight_kg": 71}, ensure_ascii=False),
             "合格", "待检"),
        ]
        row_ids = []
        for bid, subject, visit, payload, quality, status in rows:
            cur = conn.execute(
                """
                INSERT INTO visit_rows(batch_id, subject_key, visit_code, payload, quality, status)
                VALUES (?,?,?,?,?,?)
                """,
                (bid, subject, visit, payload, quality, status),
            )
            row_ids.append(cur.lastrowid)

        findings = [
            (row_ids[1], "visit_date", "一般", "必填字段缺失: visit_date", "开放"),
            (row_ids[2], "payload", "严重", "载荷为空或受试者/访视编码缺失", "开放"),
            (row_ids[4], "weight_kg", "一般", "必填字段缺失: weight_kg", "开放"),
            (row_ids[6], "subject_key", "一般", "同中心开放批内出现重复受试者访视键", "开放"),
            (row_ids[7], "payload", "严重", "载荷为空或受试者/访视编码缺失", "开放"),
            (row_ids[8], "visit_date", "一般", "必填字段缺失: visit_date", "开放"),
            (row_ids[8], "investigator", "一般", "必填字段缺失: investigator", "开放"),
            (row_ids[11], "visit_date", "一般", "历史缺字段样例", "已关闭"),
        ]
        for rid, field, sev, msg, status in findings:
            conn.execute(
                """
                INSERT INTO qc_findings(row_id, field_name, severity, message, status)
                VALUES (?,?,?,?,?)
                """,
                (rid, field, sev, msg, status),
            )

        conn.execute(
            """
            INSERT INTO backfill_jobs(job_code, row_id, status, attempt, message)
            VALUES ('BF-0001', ?, '排队', 1, '种子样例排队任务')
            """,
            (row_ids[1],),
        )
        conn.execute(
            """
            INSERT INTO backfill_jobs(job_code, row_id, status, attempt, message, finished_at)
            VALUES ('BF-0002', ?, '失败', 2, '种子样例失败任务', datetime('now'))
            """,
            (row_ids[2],),
        )

        for bid in batch_ids:
            cnt = conn.execute(
                "SELECT COUNT(*) AS c FROM visit_rows WHERE batch_id=?", (bid,)
            ).fetchone()["c"]
            gap = conn.execute(
                "SELECT COUNT(*) AS c FROM visit_rows WHERE batch_id=? AND quality!='合格'",
                (bid,),
            ).fetchone()["c"]
            conn.execute(
                "UPDATE visit_batches SET item_count=?, gap_count=? WHERE id=?",
                (cnt, gap, bid),
            )

        conn.execute(
            """
            INSERT INTO reconcile_reports(summary, gap_rows, open_findings, pending_jobs, mismatch)
            VALUES ('种子对账快照', 6, 7, 1, 2)
            """
        )
        conn.execute(
            """
            INSERT INTO audit_events(actor, action, entity_type, entity_id, detail)
            VALUES ('system', '种子初始化', 'lab', 0, '首次启动写入临床试验访视样例')
            """
        )
        try:
            from app.services.audit_arch import seed_skew
            seed_skew(db_path)
        except Exception:
            pass
        _meta_set(conn, "seeded", "1")
        _meta_set(conn, "seed_version", "clinic-1")
