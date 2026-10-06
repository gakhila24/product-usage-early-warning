"""
Flask blueprint: /api/action-center/*
Thin HTTP layer over action_center_service.py (all business logic lives there).

Every GET accepts the global filter query-string:  product, region, segment, risk, owner, horizon
"""
from flask import Blueprint, Response, jsonify, request

import action_center_service as ac

bp = Blueprint("action_center", __name__, url_prefix="/api/action-center")


def ok(data, code=200):
    return jsonify(ac._py(data)), code


def err(e, code=400):
    return jsonify({"error": str(e)}), code


def _filters():
    return ac.Filters.from_args(request.args)


def _int(name, default):
    try:
        return int(request.args.get(name, default))
    except (TypeError, ValueError):
        return default


def guarded(fn):
    """Uniform error handling: 404 for unknown ids, 400 for bad input, 500 otherwise."""
    from functools import wraps

    @wraps(fn)
    def wrapper(*a, **kw):
        try:
            return fn(*a, **kw)
        except KeyError as e:
            return err(f"not found: {e.args[0] if e.args else ''}", 404)
        except ValueError as e:
            return err(e, 400)
        except Exception as e:                                   # pragma: no cover - surfaced to the UI as a readable error
            return err(e, 500)
    return wrapper


# ------------------------------------------------------------------ meta / overview
@bp.get("/filters")
@guarded
def r_filters():
    return ok(ac.filter_options())


@bp.get("/overview")
@guarded
def r_overview():
    return ok(ac.overview(_filters()))


@bp.get("/trend")
@guarded
def r_trend():
    return ok(ac.health_trend(_filters(), request.args.get("grain", "daily")))


@bp.get("/at-risk")
@guarded
def r_at_risk():
    return ok(ac.at_risk_accounts(_filters(), _int("page", 1), _int("page_size", 6), request.args.get("q", ""), request.args.get("sort", "health")))


@bp.get("/portfolio")
@guarded
def r_portfolio():
    return ok(ac.portfolio(_filters()))


@bp.get("/queue")
@guarded
def r_queue():
    return ok(ac.action_queue(_filters(), _int("page", 1), _int("page_size", 6), request.args.get("q", ""), request.args.get("level")))


@bp.get("/accounts/<account_id>")
@guarded
def r_account(account_id):
    return ok(ac.account_context(account_id))


# ------------------------------------------------------------------ follow-ups
@bp.get("/followups")
@guarded
def r_followups():
    return ok(ac.list_followups(_filters(), request.args.get("role"), request.args.get("q", "")))


@bp.post("/followups")
@guarded
def r_followup_create():
    return ok(ac.create_followup(request.get_json(force=True) or {}), 201)


@bp.post("/followups/reset")
@guarded
def r_followup_reset():
    return ok({"seeded": ac.seed_followups()})


@bp.patch("/followups/<fid>")
@guarded
def r_followup_patch(fid):
    return ok(ac.update_followup(fid, request.get_json(force=True) or {}))


@bp.post("/followups/<fid>/advance")
@guarded
def r_followup_advance(fid):
    return ok(ac.advance_followup(fid))


@bp.delete("/followups/<fid>")
@guarded
def r_followup_delete(fid):
    if not ac.delete_followup(fid):
        raise KeyError(fid)
    return ok({"deleted": fid})


@bp.get("/followups/<fid>/events")
@guarded
def r_followup_events(fid):
    return ok({"events": ac.followup_events(fid)})


# ------------------------------------------------------------------ analytics pages
@bp.get("/interventions")
@guarded
def r_interventions():
    return ok(ac.intervention_effectiveness(_filters(), request.args.get("outcome", "all"), _int("page", 1), _int("page_size", 8)))


@bp.get("/interventions/export")
@guarded
def r_interventions_export():
    return Response(ac.intervention_csv(_filters()), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=intervention-effectiveness.csv"})


@bp.get("/health-scores")
@guarded
def r_health_scores():
    return ok(ac.health_scores(_filters()))


@bp.get("/rfm")
@guarded
def r_rfm():
    return ok(ac.rfm(_filters(), request.args.get("segment", "all"), request.args.get("q", ""), _int("page", 1), _int("page_size", 8)))


@bp.get("/drivers")
@guarded
def r_drivers():
    return ok(ac.drivers(_filters()))


@bp.get("/renewals")
@guarded
def r_renewals():
    return ok(ac.renewals(_filters(), _int("horizon", 90), _int("page", 1), _int("page_size", 8), sort=request.args.get("sort", "days")))


@bp.get("/segments")
@guarded
def r_segments():
    return ok(ac.segments(_filters()))


@bp.get("/explorer")
@guarded
def r_explorer():
    return ok(ac.explorer(_filters(), _int("page", 1), _int("page_size", 10), request.args.get("q", ""), request.args.get("sort", "health")))


@bp.get("/explorer/export")
@guarded
def r_explorer_export():
    return Response(ac.explorer_csv(_filters(), request.args.get("q", "")), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=account-records.csv"})


# ------------------------------------------------------------------ alerts
@bp.get("/alerts")
@guarded
def r_alerts():
    return ok(ac.alerts(request.args.get("status", "all"), request.args.get("severity", "all")))


@bp.post("/alerts/review-all")
@guarded
def r_alerts_review_all():
    return ok(ac.review_all_alerts())


@bp.post("/alerts/reopen")
@guarded
def r_alerts_reopen():
    return ok(ac.reopen_alerts())


@bp.post("/alerts/<aid>/review")
@guarded
def r_alert_review(aid):
    return ok(ac.review_alert(aid))


# ------------------------------------------------------------------ playbooks
@bp.get("/playbooks")
@guarded
def r_playbooks():
    return ok({"playbooks": ac.playbooks(_filters())})


@bp.post("/playbooks/<pid>/launch")
@guarded
def r_playbook_launch(pid):
    body = request.get_json(force=True) or {}
    if not body.get("accountId"):
        raise ValueError("accountId is required")
    return ok(ac.launch_playbook(pid, body["accountId"], body.get("due")), 201)


# ------------------------------------------------------------------ reports
@bp.get("/reports")
@guarded
def r_reports():
    return ok(ac.list_reports())


@bp.post("/reports")
@guarded
def r_report_create():
    return ok(ac.create_report(request.get_json(force=True) or {}), 201)


@bp.get("/reports/<rid>")
@guarded
def r_report_get(rid):
    return ok(ac.get_report(rid))


@bp.get("/reports/<rid>/download")
@guarded
def r_report_download(rid):
    return Response(ac.report_html(rid), mimetype="text/html",
                    headers={"Content-Disposition": f"attachment; filename={rid}.html"})


# ------------------------------------------------------------------ static content / settings
@bp.get("/methodology")
@guarded
def r_methodology():
    return ok(ac.methodology())


@bp.get("/faqs")
@guarded
def r_faqs():
    return ok(ac.faqs())


@bp.get("/settings")
@guarded
def r_settings():
    return ok(ac.get_settings())


@bp.put("/settings")
@guarded
def r_settings_put():
    return ok(ac.put_settings(request.get_json(force=True) or {}))
