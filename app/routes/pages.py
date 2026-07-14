"""HTML pages: dashboard, employees, schedule viewer/editor."""

from __future__ import annotations

from flask import Blueprint, make_response, redirect, render_template, request, url_for

from app.config import config
from app.services import employees, preferences, priority, scheduler, swaps
from app.utils.dates import format_date_he, next_week_id, week_dates
from app.utils.hebrew import DAYS_HE, PREF_LABELS_HE, SHIFTS_HE

bp = Blueprint("pages", __name__)


def _token_ok() -> bool:
    token = request.args.get("token") or request.cookies.get("admin_token")
    return bool(token and token == config.ADMIN_TOKEN)


def _require_page_auth():
    if _token_ok():
        return None
    return redirect(url_for("pages.login", next=request.path))


@bp.get("/login")
def login():
    err = None
    if request.args.get("error"):
        err = "אסימון שגוי"
    return render_template("login.html", error=err)


@bp.post("/login")
def login_post():
    token = request.form.get("token", "")
    nxt = request.form.get("next") or "/"
    if token != config.ADMIN_TOKEN:
        return redirect(url_for("pages.login", error="1"))
    resp = make_response(redirect(nxt))
    resp.set_cookie("admin_token", token, httponly=True, samesite="Lax", max_age=60 * 60 * 24 * 30)
    return resp


@bp.get("/")
def dashboard():
    gate = _require_page_auth()
    if gate:
        return gate
    week = request.args.get("week") or next_week_id()
    emps = employees.list_employees()
    sched = scheduler.get_schedule(week)
    prefs = preferences.list_preferences_for_week(week)
    submitted = sum(1 for p in prefs if p.get("submitted"))
    return render_template(
        "dashboard.html",
        employees=emps,
        week=week,
        schedule=scheduler.enrich_schedule(sched) if sched else None,
        prefs_count=len(prefs),
        submitted_count=submitted,
        days=DAYS_HE,
        shifts=SHIFTS_HE,
        dates=week_dates(week),
        format_date_he=format_date_he,
        admin_token=config.ADMIN_TOKEN,
    )


@bp.get("/employees")
def employees_page():
    gate = _require_page_auth()
    if gate:
        return gate
    return render_template(
        "employees.html",
        employees=employees.list_employees(),
        admin_token=config.ADMIN_TOKEN,
    )


@bp.get("/schedule")
def schedule_viewer():
    gate = _require_page_auth()
    if gate:
        return gate
    week = request.args.get("week") or next_week_id()
    sched = scheduler.get_schedule(week)
    enriched = scheduler.enrich_schedule(sched) if sched else None
    dates = week_dates(week)
    date_labels = {DAYS_HE[i]: format_date_he(dates[i]) for i in range(7)}
    return render_template(
        "schedule.html",
        week=week,
        schedule=enriched,
        days=DAYS_HE,
        shifts=SHIFTS_HE,
        date_labels=date_labels,
        edit_mode=False,
        employees=employees.list_employees(active_only=True),
        admin_token=config.ADMIN_TOKEN,
    )


@bp.get("/schedule/edit")
def schedule_editor():
    gate = _require_page_auth()
    if gate:
        return gate
    week = request.args.get("week") or next_week_id()
    sched = scheduler.get_schedule(week)
    enriched = scheduler.enrich_schedule(sched) if sched else {
        "weekId": week,
        "grid": scheduler.empty_schedule_grid(),
        "enriched": {
            d: {s: [] for s in SHIFTS_HE} for d in DAYS_HE
        },
        "warnings": [],
        "status": "draft",
        "published": False,
    }
    dates = week_dates(week)
    date_labels = {DAYS_HE[i]: format_date_he(dates[i]) for i in range(7)}
    return render_template(
        "schedule.html",
        week=week,
        schedule=enriched,
        days=DAYS_HE,
        shifts=SHIFTS_HE,
        date_labels=date_labels,
        edit_mode=True,
        employees=employees.list_employees(active_only=True),
        admin_token=config.ADMIN_TOKEN,
    )


@bp.get("/preferences")
def preferences_page():
    gate = _require_page_auth()
    if gate:
        return gate
    week = request.args.get("week") or next_week_id()
    prefs = preferences.list_preferences_for_week(week)
    emp_map = {e["id"]: e for e in employees.list_employees()}
    rows = []
    for p in prefs:
        emp = emp_map.get(p.get("employeeId"))
        rows.append({**p, "employeeName": emp["name"] if emp else "?", "gender": emp.get("gender") if emp else None})
    return render_template(
        "preferences.html",
        week=week,
        preferences=rows,
        days=DAYS_HE,
        shifts=SHIFTS_HE,
        pref_labels=PREF_LABELS_HE,
        admin_token=config.ADMIN_TOKEN,
    )


@bp.get("/priority")
def priority_history_page():
    gate = _require_page_auth()
    if gate:
        return gate
    week = request.args.get("week") or ""
    rows = priority.list_priority_history(week=week or None)
    emp_map = {e["id"]: e for e in employees.list_employees()}
    for r in rows:
        if not r.get("nurse_name"):
            emp = emp_map.get(r.get("nurse_id"))
            r["nurse_name"] = emp["name"] if emp else r.get("nurse_id")
    weeks = sorted({r.get("week") for r in priority.list_priority_history() if r.get("week")}, reverse=True)
    return render_template(
        "priority_history.html",
        week=week,
        rows=rows,
        weeks=weeks,
        score_map=priority.SCORE_BY_SATISFIED,
        admin_token=config.ADMIN_TOKEN,
    )


@bp.get("/swaps")
def swaps_page():
    gate = _require_page_auth()
    if gate:
        return gate
    week = request.args.get("week") or ""
    pending = [
        swaps.enrich_swap(s)
        for s in swaps.list_swaps(week=week or None, pending_only=True)
    ]
    history = [
        swaps.enrich_swap(s)
        for s in swaps.list_swaps(week=week or None)
        if s.get("status") in (swaps.STATUS_APPROVED, swaps.STATUS_REJECTED)
    ]
    audit = swaps.list_swap_audit()[:50]
    weeks = sorted({s.get("week") for s in swaps.list_swaps() if s.get("week")}, reverse=True)
    return render_template(
        "swaps.html",
        week=week,
        weeks=weeks,
        pending=pending,
        history=history,
        audit=audit,
        admin_token=config.ADMIN_TOKEN,
    )
