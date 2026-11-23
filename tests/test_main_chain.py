from app.services import backfill, qc, reconcile, visits


def test_qc_backfill_reconcile_chain(db_path):
    batches = visits.list_batches(db_path)
    batch = next(b for b in batches if b["status"] == "采集中")
    scanned = qc.scan_batch(batch["id"], db_path=db_path)
    assert scanned["created"] >= 0
    detail = visits.get_batch(batch["id"], db_path)
    gap = next(
        (
            r
            for r in detail["items"]
            if r["quality"] != "合格" and r["status"] in ("待检", "待补采")
        ),
        None,
    )
    assert gap is not None
    job = backfill.enqueue_from_row(gap["id"], db_path=db_path)
    assert job["status"] == "排队"
    done = backfill.run_job(job["id"], succeed=True, db_path=db_path)
    assert done["status"] == "成功"
    row = visits.list_rows(db_path=db_path, batch_id=batch["id"])
    fixed = next(r for r in row if r["id"] == gap["id"])
    assert fixed["quality"] == "合格"
    assert fixed["status"] == "已入库"
    report = reconcile.run_reconcile(db_path)
    assert "缺口行" in report["summary"]
    assert "detail" in report


def test_mock_crawl_and_ingest(db_path):
    batches = visits.list_batches(db_path)
    batch = next(b for b in batches if b["status"] == "采集中")
    before = visits.get_batch(batch["id"], db_path)["item_count"]
    crawled = visits.mock_crawl(batch["id"], count=3, mix_bad=True, db_path=db_path)
    assert crawled["created"] == 3
    after = visits.get_batch(batch["id"], db_path)
    assert after["item_count"] >= before + 3
    ingested = visits.ingest_ok_rows(batch["id"], db_path=db_path)
    assert ingested["ingested"] >= 0
