from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import parse_qs

import cherrypy
from itsdangerous import BadSignature, URLSafeSerializer

from app.config import Config
from app.seed import seed_if_needed
from app.services import audit as audit_svc
from app.services import backfill as backfill_svc
from app.services import protocols as protocols_svc
from app.services import qc as qc_svc
from app.services import reconcile as reconcile_svc
from app.services import settings as settings_svc
from app.services import audit_arch as audit_arch_svc
from app.services import audit_arch_cutover as audit_arch_cutover_svc
from app.services import audit_arch_dualwrite as audit_arch_dual_svc
from app.services import sites as sites_svc
from app.services import visits as visits_svc
from app.services.errors import ServiceError

STATIC = Path(__file__).resolve().parent.parent / "static"
serializer = URLSafeSerializer(Config.SECRET, salt="cc-clinic-session")


def _json(data, status: int = 200):
    cherrypy.response.status = status
    cherrypy.response.headers["Content-Type"] = "application/json; charset=utf-8"
    return json.dumps(data, ensure_ascii=False).encode("utf-8")


def _read_json() -> dict:
    try:
        length = int(cherrypy.request.headers.get("Content-Length", 0) or 0)
    except ValueError:
        length = 0
    if length <= 0:
        return {}
    body = cherrypy.request.body.read(length)
    if not body:
        return {}
    try:
        data = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _query() -> dict:
    raw = cherrypy.request.query_string or ""
    parsed = parse_qs(raw, keep_blank_values=False)
    return {k: v[0] if len(v) == 1 else v for k, v in parsed.items()}


def _current_user() -> str | None:
    raw = cherrypy.request.cookie.get(Config.COOKIE_NAME)
    if not raw:
        return None
    try:
        data = serializer.loads(raw.value)
    except BadSignature:
        return None
    if isinstance(data, dict) and data.get("user") == Config.ADMIN_USER:
        return data["user"]
    return None


def _require() -> str:
    user = _current_user()
    if not user:
        raise ServiceError("未登录", 401)
    return user


def _set_session_cookie(token: str) -> None:
    cherrypy.response.cookie[Config.COOKIE_NAME] = token
    cherrypy.response.cookie[Config.COOKIE_NAME]["path"] = "/"
    cherrypy.response.cookie[Config.COOKIE_NAME]["max-age"] = 86400 * 7
    cherrypy.response.cookie[Config.COOKIE_NAME]["httponly"] = True


def _clear_session_cookie() -> None:
    cherrypy.response.cookie[Config.COOKIE_NAME] = ""
    cherrypy.response.cookie[Config.COOKIE_NAME]["path"] = "/"
    cherrypy.response.cookie[Config.COOKIE_NAME]["max-age"] = 0
    cherrypy.response.cookie[Config.COOKIE_NAME]["expires"] = 0


def _file(name: str):
    path = STATIC / name
    return cherrypy.lib.static.serve_file(
        str(path), content_type="text/html; charset=utf-8"
    )


def _wrap(fn):
    def inner(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except ServiceError as exc:
            return _json({"error": exc.message}, exc.status_code)
        except Exception as exc:  # noqa: BLE001 — surface unexpected API errors
            return _json({"error": f"服务器错误: {exc}"}, 500)

    return inner


class Root:
    @cherrypy.expose
    def index(self):
        if _current_user():
            raise cherrypy.HTTPRedirect("/app")
        raise cherrypy.HTTPRedirect("/login")

    @cherrypy.expose
    def login(self):
        return _file("login.html")

    @cherrypy.expose
    def app(self, *args):
        if not _current_user():
            raise cherrypy.HTTPRedirect("/login")
        return _file("index.html")


class Api:
    @cherrypy.expose
    @_wrap
    def login(self):
        if cherrypy.request.method != "POST":
            return _json({"error": "方法不允许"}, 405)
        body = _read_json()
        if body.get("username") == Config.ADMIN_USER and body.get("password") == Config.ADMIN_PASS:
            token = serializer.dumps({"user": Config.ADMIN_USER})
            resp = _json({"ok": True, "user": Config.ADMIN_USER})
            _set_session_cookie(token)
            return resp
        return _json({"error": "用户名或密码错误"}, 401)

    @cherrypy.expose
    @_wrap
    def logout(self):
        if cherrypy.request.method != "POST":
            return _json({"error": "方法不允许"}, 405)
        resp = _json({"ok": True})
        _clear_session_cookie()
        return resp

    @cherrypy.expose
    @_wrap
    def me(self):
        user = _current_user()
        if not user:
            return _json({"error": "未登录"}, 401)
        return _json({"user": user})

    @cherrypy.expose
    @_wrap
    def dashboard(self):
        _require()
        return _json(reconcile_svc.dashboard())

    @cherrypy.expose
    @_wrap
    def sites(self, site_id=None, action=None):
        _require()
        method = cherrypy.request.method
        q = _query()
        if site_id is None:
            if method == "GET":
                status = q.get("status")
                return _json({"items": sites_svc.list_sites(status=status)})
            if method == "POST":
                body = _read_json()
                return _json(
                    sites_svc.create_site(
                        body.get("name", ""),
                        int(body.get("quota") or 50),
                        body.get("region", ""),
                        body.get("principal", ""),
                        body.get("note", ""),
                    )
                )
            return _json({"error": "方法不允许"}, 405)
        sid = int(site_id)
        if action == "status" and method == "POST":
            body = _read_json()
            return _json(sites_svc.set_status(sid, body.get("status", "")))
        if action == "quota" and method == "POST":
            body = _read_json()
            return _json(sites_svc.update_quota(sid, int(body.get("quota") or 1)))
        if action == "note" and method == "POST":
            body = _read_json()
            return _json(
                sites_svc.update_note(
                    sid,
                    body.get("note", ""),
                    body.get("principal", ""),
                    body.get("region", ""),
                )
            )
        if action is None and method == "GET":
            return _json(sites_svc.get_site(sid))
        return _json({"error": "未知试验中心路由"}, 404)

    @cherrypy.expose
    @_wrap
    def site_counts(self):
        _require()
        return _json(sites_svc.status_counts())

    @cherrypy.expose
    @_wrap
    def protocols(self, protocol_id=None, action=None):
        _require()
        method = cherrypy.request.method
        q = _query()
        if protocol_id is None:
            if method == "GET":
                return _json(
                    {"items": protocols_svc.list_protocols(status=q.get("status"))}
                )
            if method == "POST":
                body = _read_json()
                return _json(
                    protocols_svc.create_protocol(
                        body.get("title", ""),
                        body.get("version", "1.0"),
                        body.get("required_fields"),
                        body.get("visit_codes"),
                        body.get("note", ""),
                    )
                )
            return _json({"error": "方法不允许"}, 405)
        pid = int(protocol_id)
        if action == "status" and method == "POST":
            body = _read_json()
            return _json(protocols_svc.set_status(pid, body.get("status", "")))
        if action == "fields" and method == "POST":
            body = _read_json()
            return _json(
                protocols_svc.update_fields(
                    pid,
                    body.get("required_fields"),
                    body.get("visit_codes"),
                    body.get("note"),
                )
            )
        if action is None and method == "GET":
            return _json(protocols_svc.get_protocol(pid))
        return _json({"error": "未知方案路由"}, 404)

    @cherrypy.expose
    @_wrap
    def batches(self, batch_id=None, action=None):
        _require()
        method = cherrypy.request.method
        q = _query()
        if batch_id is None:
            if method == "GET":
                site_id = int(q["site_id"]) if q.get("site_id") else None
                return _json(
                    {
                        "items": visits_svc.list_batches(
                            site_id=site_id, status=q.get("status")
                        )
                    }
                )
            if method == "POST":
                body = _read_json()
                return _json(
                    visits_svc.create_batch(
                        int(body.get("site_id") or 0),
                        int(body["protocol_id"]) if body.get("protocol_id") else None,
                        body.get("note", ""),
                    )
                )
            return _json({"error": "方法不允许"}, 405)
        bid = int(batch_id)
        if action == "items" and method == "POST":
            body = _read_json()
            return _json(
                visits_svc.add_visit_row(
                    bid,
                    body.get("subject_key", ""),
                    body.get("visit_code", ""),
                    body.get("payload", ""),
                    body.get("quality"),
                )
            )
        if action == "crawl" and method == "POST":
            body = _read_json()
            return _json(
                visits_svc.mock_crawl(
                    bid,
                    int(body.get("count") or 5),
                    bool(body.get("mix_bad", True)),
                )
            )
        if action == "close" and method == "POST":
            return _json(visits_svc.close_batch(bid))
        if action == "complete" and method == "POST":
            return _json(visits_svc.mark_batch_complete(bid))
        if action == "ingest" and method == "POST":
            return _json(visits_svc.ingest_ok_rows(bid))
        if action == "qc" and method == "POST":
            return _json(qc_svc.scan_batch(bid))
        if action == "backfill" and method == "POST":
            return _json(backfill_svc.enqueue_gaps_for_batch(bid))
        if action is None and method == "GET":
            return _json(visits_svc.get_batch(bid))
        return _json({"error": "未知批次路由"}, 404)

    @cherrypy.expose
    @_wrap
    def rows(self, row_id=None, action=None):
        _require()
        method = cherrypy.request.method
        q = _query()
        if row_id is None:
            if method != "GET":
                return _json({"error": "方法不允许"}, 405)
            batch_id = int(q["batch_id"]) if q.get("batch_id") else None
            return _json(
                {
                    "items": visits_svc.list_rows(
                        batch_id=batch_id,
                        quality=q.get("quality"),
                        status=q.get("status"),
                    )
                }
            )
        rid = int(row_id)
        if action == "status" and method == "POST":
            body = _read_json()
            return _json(visits_svc.set_row_status(rid, body.get("status", "")))
        if action == "enqueue" and method == "POST":
            return _json(backfill_svc.enqueue_from_row(rid))
        return _json({"error": "未知访视行路由"}, 404)

    @cherrypy.expose
    @_wrap
    def findings(self, finding_id=None, action=None):
        _require()
        method = cherrypy.request.method
        q = _query()
        if finding_id is None:
            if method == "GET":
                row_id = int(q["row_id"]) if q.get("row_id") else None
                return _json(
                    {
                        "items": qc_svc.list_findings(
                            status=q.get("status"),
                            row_id=row_id,
                            severity=q.get("severity"),
                        ),
                        "summary": qc_svc.summary(),
                    }
                )
            if method == "POST":
                body = _read_json()
                if body.get("scan_all"):
                    return _json(qc_svc.scan_all_open())
                if body.get("batch_id"):
                    return _json(qc_svc.scan_batch(int(body["batch_id"])))
                return _json({"error": "缺少扫描目标"}, 400)
            return _json({"error": "方法不允许"}, 405)
        fid = int(finding_id)
        if action == "close" and method == "POST":
            return _json(qc_svc.close_finding(fid))
        if action == "reopen" and method == "POST":
            return _json(qc_svc.reopen_finding(fid))
        if action is None and method == "GET":
            return _json(qc_svc.get_finding(fid))
        return _json({"error": "未知质控路由"}, 404)

    @cherrypy.expose
    @_wrap
    def jobs(self, job_id=None, action=None):
        _require()
        method = cherrypy.request.method
        q = _query()
        if job_id is None:
            if method == "GET":
                row_id = int(q["row_id"]) if q.get("row_id") else None
                return _json(
                    {
                        "items": backfill_svc.list_jobs(
                            status=q.get("status"), row_id=row_id
                        ),
                        "summary": backfill_svc.summary(),
                    }
                )
            if method == "POST":
                body = _read_json()
                return _json(backfill_svc.enqueue_from_row(int(body.get("row_id") or 0)))
            return _json({"error": "方法不允许"}, 405)
        jid = int(job_id)
        if action == "run" and method == "POST":
            body = _read_json()
            return _json(
                backfill_svc.run_job(jid, succeed=bool(body.get("succeed", True)))
            )
        if action == "retry" and method == "POST":
            return _json(backfill_svc.retry_job(jid))
        if action is None and method == "GET":
            return _json(backfill_svc.get_job(jid))
        return _json({"error": "未知补采路由"}, 404)

    @cherrypy.expose
    @_wrap
    def reports(self, action=None):
        _require()
        method = cherrypy.request.method
        if action == "run" and method == "POST":
            return _json(reconcile_svc.run_reconcile())
        if action == "matrix" and method == "GET":
            return _json({"items": reconcile_svc.site_gap_matrix()})
        if action is None and method == "GET":
            return _json({"items": reconcile_svc.list_reports()})
        return _json({"error": "未知对账路由"}, 404)

    @cherrypy.expose
    @_wrap
    def settings(self, action=None):
        _require()
        method = cherrypy.request.method
        if action == "update" and method == "POST":
            body = _read_json()
            return _json(
                settings_svc.update_setting(body.get("key", ""), body.get("value", ""))
            )
        if action is None and method == "GET":
            return _json(
                {
                    "items": settings_svc.list_settings(),
                    "snapshot": settings_svc.bulk_snapshot(),
                }
            )
        return _json({"error": "未知设置路由"}, 404)


    @cherrypy.expose
    @_wrap
    def audit_arch_dash(self):
        _require()
        return _json(audit_arch_cutover_svc.board())

    @cherrypy.expose
    @_wrap
    def audit_arch_commit(self):
        _require()
        body = _read_json()
        return _json(audit_arch_svc.commit_action(body))

    @cherrypy.expose
    @_wrap
    def audit_arch_half(self):
        _require()
        return _json(audit_arch_svc.reconcile_display())

    @cherrypy.expose
    @_wrap
    def audit_arch_snap(self):
        _require()
        return _json(audit_arch_svc.snapshot())

    @cherrypy.expose
    @_wrap
    def audit_arch_cutover(self):
        _require()
        body = _read_json()
        return _json(
            audit_arch_cutover_svc.append_cutover(
                int(body.get("ref_id") or 0),
                str(body.get("note") or "归档钉定"),
            )
        )

    @cherrypy.expose
    @_wrap
    def audit_arch_dual(self):
        _require()
        body = _read_json()
        return _json(audit_arch_dual_svc.apply_dualwrite(str(body.get("note") or "归档钉定")))

    @cherrypy.expose
    @_wrap
    def audits(self):
        _require()
        q = _query()
        limit = int(q.get("limit") or 100)
        return _json(
            {"items": audit_svc.list_events(limit), "summary": audit_svc.summary()}
        )


class ApiMount:
    """Flat REST dispatcher mounted at /api."""

    @cherrypy.expose
    def default(self, *vpath, **params):
        path = "/" + "/".join(str(p) for p in vpath)
        api = Api()
        if path in ("/login",) or path == "login":
            return api.login()
        if path in ("/logout",) or path == "logout":
            return api.logout()
        if path in ("/me",) or path == "me":
            return api.me()
        if path in ("/dashboard",) or path == "dashboard":
            return api.dashboard()
        if path in ("/site-counts",) or path == "site-counts":
            return api.site_counts()
        if path == "/sites" or path.startswith("/sites/"):
            parts = path.strip("/").split("/")
            if len(parts) == 1:
                return api.sites()
            if len(parts) == 2:
                return api.sites(site_id=parts[1])
            return api.sites(site_id=parts[1], action=parts[2])
        if path == "/protocols" or path.startswith("/protocols/"):
            parts = path.strip("/").split("/")
            if len(parts) == 1:
                return api.protocols()
            if len(parts) == 2:
                return api.protocols(protocol_id=parts[1])
            return api.protocols(protocol_id=parts[1], action=parts[2])
        if path == "/batches" or path.startswith("/batches/"):
            parts = path.strip("/").split("/")
            if len(parts) == 1:
                return api.batches()
            if len(parts) == 2:
                return api.batches(batch_id=parts[1])
            return api.batches(batch_id=parts[1], action=parts[2])
        if path == "/rows" or path.startswith("/rows/"):
            parts = path.strip("/").split("/")
            if len(parts) == 1:
                return api.rows()
            if len(parts) == 2:
                return api.rows(row_id=parts[1])
            return api.rows(row_id=parts[1], action=parts[2])
        if path == "/findings" or path.startswith("/findings/"):
            parts = path.strip("/").split("/")
            if len(parts) == 1:
                return api.findings()
            if len(parts) == 2:
                return api.findings(finding_id=parts[1])
            return api.findings(finding_id=parts[1], action=parts[2])
        if path == "/jobs" or path.startswith("/jobs/"):
            parts = path.strip("/").split("/")
            if len(parts) == 1:
                return api.jobs()
            if len(parts) == 2:
                return api.jobs(job_id=parts[1])
            return api.jobs(job_id=parts[1], action=parts[2])
        if path == "/reports" or path.startswith("/reports/"):
            parts = path.strip("/").split("/")
            if len(parts) == 1:
                return api.reports()
            return api.reports(action=parts[1])
        if path == "/settings" or path.startswith("/settings/"):
            parts = path.strip("/").split("/")
            if len(parts) == 1:
                return api.settings()
            return api.settings(action=parts[1])
        if path == "/audits" or path.startswith("/audits"):
            return api.audits()

        if path == "/audit_arch" or path.startswith("/audit_arch/"):
            parts = path.strip("/").split("/")
            action = parts[1] if len(parts) > 1 else "dash"
            if action in ("dash", ""):
                return api.audit_arch_dash()
            if action == "commit":
                return api.audit_arch_commit()
            if action == "half":
                return api.audit_arch_half()
            if action == "snap":
                return api.audit_arch_snap()
            if action == "cutover":
                return api.audit_arch_cutover()
            if action == "dual":
                return api.audit_arch_dual()
            return _json({"error": "未知归档钉定路由"}, 404)

        return _json({"error": f"未知接口 {path}"}, 404)


def create_app():
    seed_if_needed()
    root = Root()
    conf = {
        "/": {
            "tools.encode.on": True,
            "tools.encode.encoding": "utf-8",
        },
        "/static": {
            "tools.staticdir.on": True,
            "tools.staticdir.dir": str(STATIC),
        },
    }
    cherrypy.tree.mount(root, "/", conf)
    cherrypy.tree.mount(ApiMount(), "/api", {"/": {"tools.encode.on": False}})
    return cherrypy.tree
