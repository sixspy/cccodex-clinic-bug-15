from app.services import protocols, reconcile, settings, sites, visits


def test_seed_has_core_entities(db_path):
    site_list = sites.list_sites(db_path)
    assert len(site_list) >= 3
    protos = protocols.list_protocols(db_path)
    assert len(protos) >= 2
    batches = visits.list_batches(db_path)
    assert len(batches) >= 2
    assert settings.list_settings(db_path)


def test_dashboard_counts(db_path):
    dash = reconcile.dashboard(db_path)
    assert dash["sites"] >= 3
    assert dash["batches"] >= 2
    assert dash["rows"] >= 5
    assert dash["open_findings"] >= 1
