import json

import pytest

from app.services import protocols, sites, visits
from app.services.errors import ServiceError


def test_create_site_and_toggle(db_path):
    site = sites.create_site(
        "测试新建中心",
        quota=40,
        region="杭州",
        principal="测试员",
        note="单元测试",
        db_path=db_path,
    )
    assert site["status"] == "启用"
    assert site["site_code"].startswith("SITE-")
    observed = sites.set_status(site["id"], "观察", db_path=db_path)
    assert observed["status"] == "观察"
    bumped = sites.update_quota(site["id"], 55, db_path=db_path)
    assert bumped["quota"] == 55


def test_create_batch_append_row(db_path):
    enabled = next(s for s in sites.list_sites(db_path) if s["status"] == "启用")
    active = protocols.active_protocol(db_path)
    batch = visits.create_batch(
        enabled["id"],
        protocol_id=active["id"] if active else None,
        note="测试批次",
        db_path=db_path,
    )
    assert batch["status"] == "采集中"
    ok = visits.add_visit_row(
        batch["id"],
        "T-9001",
        "V1",
        payload=json.dumps(
            {
                "visit_date": "2026-11-20",
                "investigator": "测试医生",
                "weight_kg": 61,
            },
            ensure_ascii=False,
        ),
        db_path=db_path,
    )
    assert ok["quality"] == "合格"
    bad = visits.add_visit_row(
        batch["id"],
        "T-9002",
        "V2",
        payload=json.dumps({"visit_date": "", "investigator": "测试医生"}, ensure_ascii=False),
        db_path=db_path,
    )
    assert bad["quality"] == "缺字段"
    with pytest.raises(ServiceError):
        visits.add_visit_row(
            batch["id"],
            "T-9001",
            "V1",
            payload="{}",
            db_path=db_path,
        )


def test_disabled_site_cannot_open_batch(db_path):
    disabled = next(s for s in sites.list_sites(db_path) if s["status"] == "停用")
    with pytest.raises(ServiceError):
        visits.create_batch(disabled["id"], db_path=db_path)
