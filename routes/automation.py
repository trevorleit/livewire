from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify

from database import get_db
from services.group_service import (
    create_group,
    update_group,
    delete_group,
    add_machine_to_group,
    remove_machine_from_group,
    fetch_groups_with_members,
)
from services.scheduler_service import (
    create_scheduled_job,
    set_job_enabled,
    normalize_payload,
    run_due_jobs,
    run_job_now,
)

automation_bp = Blueprint("automation", __name__)


def _build_target_label(job, machine_map, group_map):
    target_type = (job["target_type"] or "").strip()
    target_id = job["target_id"]

    if target_type == "machine":
        machine_name = machine_map.get(target_id)
        return f"Machine: {machine_name}" if machine_name else f"Machine #{target_id}"

    if target_type == "group":
        group_name = group_map.get(target_id)
        return f"Group: {group_name}" if group_name else f"Group #{target_id}"

    if target_type == "all":
        return "All Machines"

    return f"{target_type or 'Unknown'} #{target_id}" if target_id is not None else (target_type or "Unknown")


def _safe_int(value, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _clean_text(value, fallback=""):
    return str(value or fallback).strip()


def _fetch_job_by_id(cur, job_id):
    cur.execute(
        """
        SELECT *
        FROM scheduled_jobs
        WHERE id = ?
        """,
        (job_id,),
    )
    return cur.fetchone()


def _parse_dt(value):
    if not value:
        return None

    text = str(value).strip()
    if not text:
        return None

    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text[:19], fmt)
        except ValueError:
            continue

    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None


def _build_summary(jobs, recent_runs):
    now = datetime.utcnow()

    overdue_jobs = 0
    no_schedule_jobs = 0

    for j in jobs:
        if not j["enabled"]:
            continue

        next_run = _parse_dt(j.get("next_run_at"))
        if not next_run:
            no_schedule_jobs += 1
            continue

        if next_run < now:
            overdue_jobs += 1

    recent_success_runs = 0
    recent_failed_runs = 0

    for row in recent_runs:
        status = (row["status"] or "").strip().lower()
        if status in ("completed", "success", "queued"):
            recent_success_runs += 1
        elif status in ("failed", "error"):
            recent_failed_runs += 1

    return {
        "groups": 0,
        "jobs_total": len(jobs),
        "jobs_visible": 0,
        "jobs_enabled": sum(1 for j in jobs if j["enabled"]),
        "jobs_disabled": sum(1 for j in jobs if not j["enabled"]),
        "recent_runs": len(recent_runs),
        "group_members": 0,
        "overdue_jobs": overdue_jobs,
        "no_schedule_jobs": no_schedule_jobs,
        "recent_success_runs": recent_success_runs,
        "recent_failed_runs": recent_failed_runs,
    }


def _load_automation_data(search_text="", status_filter="all", target_filter="all"):
    conn = get_db()
    try:
        cur = conn.cursor()

        cur.execute(
            """
            SELECT id, hostname, display_name, is_online, machine_role
            FROM machines
            ORDER BY COALESCE(display_name, hostname) ASC
            """
        )
        machines = cur.fetchall()

        groups = fetch_groups_with_members(cur)

        cur.execute(
            """
            SELECT *
            FROM scheduled_jobs
            ORDER BY id DESC
            """
        )
        jobs = cur.fetchall()

        cur.execute(
            """
            SELECT r.*, j.job_name
            FROM scheduled_job_runs r
            LEFT JOIN scheduled_jobs j ON j.id = r.job_id
            ORDER BY r.id DESC
            LIMIT 40
            """
        )
        recent_runs = cur.fetchall()

    finally:
        conn.close()

    machine_map = {
        row["id"]: (row["display_name"] or row["hostname"])
        for row in machines
    }

    group_map = {
        row["id"]: row["group_name"]
        for row in groups
    }

    summary = _build_summary(jobs, recent_runs)
    summary["groups"] = len(groups)
    summary["group_members"] = sum(len(g["members"]) for g in groups)

    now = datetime.utcnow()
    job_cards = []

    for job in jobs:
        job_data = dict(job)
        job_data["target_label"] = _build_target_label(job, machine_map, group_map)

        next_run_dt = _parse_dt(job_data.get("next_run_at"))
        job_data["is_overdue"] = bool(job_data.get("enabled") and next_run_dt and next_run_dt < now)
        job_data["has_schedule"] = next_run_dt is not None

        haystack = " ".join([
            str(job_data.get("job_name") or ""),
            str(job_data.get("description") or ""),
            str(job_data.get("target_label") or ""),
            str(job_data.get("action_type") or ""),
            str(job_data.get("action_payload_json") or ""),
        ]).lower()

        if search_text and search_text not in haystack:
            continue

        if status_filter == "enabled" and not job_data.get("enabled"):
            continue
        if status_filter == "disabled" and job_data.get("enabled"):
            continue

        if target_filter != "all" and (job_data.get("target_type") or "").lower() != target_filter:
            continue

        job_cards.append(job_data)

    summary["jobs_visible"] = len(job_cards)

    return {
        "machines": machines,
        "groups": groups,
        "jobs": job_cards,
        "recent_runs": recent_runs,
        "summary": summary,
    }


@automation_bp.route("/automation", methods=["GET", "POST"])
def automation():
    if request.method == "POST":
        form_type = request.form.get("form_type", "").strip()

        try:
            if form_type == "create_group":
                group_name = _clean_text(request.form.get("group_name"))
                description = _clean_text(request.form.get("description"))
                color_hex = _clean_text(request.form.get("color_hex"), "#00cc66") or "#00cc66"

                if not group_name:
                    flash("Group name is required.", "warning")
                else:
                    create_group(group_name, description, color_hex)
                    flash(f'Group "{group_name}" created.', "success")

            elif form_type == "edit_group":
                group_id = _safe_int(request.form.get("group_id"))
                group_name = _clean_text(request.form.get("group_name"))
                description = _clean_text(request.form.get("description"))
                color_hex = _clean_text(request.form.get("color_hex"), "#00cc66") or "#00cc66"

                if not group_id:
                    flash("Invalid group id.", "warning")
                elif not group_name:
                    flash("Group name is required.", "warning")
                else:
                    update_group(group_id, group_name, description, color_hex)
                    flash(f'Group "{group_name}" updated.', "success")

            elif form_type == "delete_group":
                group_id = _safe_int(request.form.get("group_id"))

                if not group_id:
                    flash("Invalid group id.", "warning")
                else:
                    delete_group(group_id)
                    flash("Group deleted.", "success")

            elif form_type == "add_group_member":
                group_id = _safe_int(request.form.get("group_id"))
                machine_id = _safe_int(request.form.get("machine_id"))

                if group_id and machine_id:
                    add_machine_to_group(group_id, machine_id)
                    flash("Machine added to group.", "success")
                else:
                    flash("Invalid group or machine selection.", "warning")

            elif form_type == "remove_group_member":
                group_id = _safe_int(request.form.get("group_id"))
                machine_id = _safe_int(request.form.get("machine_id"))

                if group_id and machine_id:
                    remove_machine_from_group(group_id, machine_id)
                    flash("Machine removed from group.", "success")
                else:
                    flash("Invalid group or machine selection.", "warning")

            elif form_type == "create_job":
                job_name = _clean_text(request.form.get("job_name"))
                description = _clean_text(request.form.get("description"))
                action_type = _clean_text(request.form.get("action_type"))
                target_type = _clean_text(request.form.get("target_type"), "machine")

                machine_target_id = _safe_int(request.form.get("machine_target_id"))
                group_target_id = _safe_int(request.form.get("group_target_id"))
                interval_minutes = _safe_int(request.form.get("interval_minutes", "60"), 60)

                service_name = _clean_text(request.form.get("service_name"))
                pid = _clean_text(request.form.get("pid"))
                delay_seconds = _clean_text(request.form.get("delay_seconds"), "5")

                target_id = None
                if target_type == "machine":
                    target_id = machine_target_id
                elif target_type == "group":
                    target_id = group_target_id

                if not description and action_type and interval_minutes:
                    description = f"{action_type} every {interval_minutes} minutes"

                if not job_name:
                    flash("Job name is required.", "warning")

                elif not action_type:
                    flash("Action type is required.", "warning")

                elif target_type not in ("machine", "group"):
                    flash("Target type must be machine or group.", "warning")

                elif not target_id:
                    flash("Please select a valid target for the chosen target type.", "warning")

                elif interval_minutes is None or interval_minutes < 1:
                    flash("Interval minutes must be 1 or greater.", "warning")

                elif action_type == "restart_service" and not service_name:
                    flash("Service name is required for restart_service.", "warning")

                elif action_type == "stop_process" and not pid:
                    flash("PID is required for stop_process.", "warning")

                elif action_type == "stop_process" and not str(pid).isdigit():
                    flash("PID must be a number.", "warning")

                elif action_type == "reboot_machine" and not str(delay_seconds).isdigit():
                    flash("Delay seconds must be a number.", "warning")

                else:
                    action_payload_json = normalize_payload(
                        action_type,
                        service_name=service_name,
                        pid=pid,
                        delay_seconds=delay_seconds or "5",
                    )

                    create_scheduled_job(
                        job_name=job_name,
                        description=description,
                        target_type=target_type,
                        target_id=target_id,
                        action_type=action_type,
                        action_payload_json=action_payload_json,
                        interval_minutes=interval_minutes,
                        auto_approve=1 if request.form.get("auto_approve") == "on" else 0,
                        only_when_online=1 if request.form.get("only_when_online") == "on" else 0,
                    )
                    flash(f'Scheduled job "{job_name}" created.', "success")

            elif form_type == "edit_job":
                job_id = _safe_int(request.form.get("job_id"))
                job_name = _clean_text(request.form.get("job_name"))
                description = _clean_text(request.form.get("description"))
                target_type = _clean_text(request.form.get("target_type"), "machine")
                machine_target_id = _safe_int(request.form.get("machine_target_id"))
                group_target_id = _safe_int(request.form.get("group_target_id"))
                action_type = _clean_text(request.form.get("action_type"))
                interval_minutes = _safe_int(request.form.get("interval_minutes"), 60)
                service_name = _clean_text(request.form.get("service_name"))
                pid = _clean_text(request.form.get("pid"))
                delay_seconds = _clean_text(request.form.get("delay_seconds"), "5")
                auto_approve = 1 if request.form.get("auto_approve") == "on" else 0
                only_when_online = 1 if request.form.get("only_when_online") == "on" else 0

                target_id = None
                if target_type == "machine":
                    target_id = machine_target_id
                elif target_type == "group":
                    target_id = group_target_id

                if not description and action_type and interval_minutes:
                    description = f"{action_type} every {interval_minutes} minutes"

                if not job_id:
                    flash("Invalid job id.", "warning")
                elif not job_name:
                    flash("Job name is required.", "warning")
                elif not action_type:
                    flash("Action type is required.", "warning")
                elif target_type not in ("machine", "group"):
                    flash("Target type must be machine or group.", "warning")
                elif not target_id:
                    flash("Please select a valid target for the chosen target type.", "warning")
                elif interval_minutes is None or interval_minutes < 1:
                    flash("Interval minutes must be 1 or greater.", "warning")
                elif action_type == "restart_service" and not service_name:
                    flash("Service name is required for restart_service.", "warning")
                elif action_type == "stop_process" and not pid:
                    flash("PID is required for stop_process.", "warning")
                elif action_type == "stop_process" and not str(pid).isdigit():
                    flash("PID must be a number.", "warning")
                elif action_type == "reboot_machine" and not str(delay_seconds).isdigit():
                    flash("Delay seconds must be a number.", "warning")
                else:
                    action_payload_json = normalize_payload(
                        action_type,
                        service_name=service_name,
                        pid=pid,
                        delay_seconds=delay_seconds or "5",
                    )

                    conn = get_db()
                    try:
                        cur = conn.cursor()
                        cur.execute(
                            """
                            UPDATE scheduled_jobs
                            SET
                                job_name = ?,
                                description = ?,
                                target_type = ?,
                                target_id = ?,
                                action_type = ?,
                                action_payload_json = ?,
                                interval_minutes = ?,
                                auto_approve = ?,
                                only_when_online = ?
                            WHERE id = ?
                            """,
                            (
                                job_name,
                                description,
                                target_type,
                                target_id,
                                action_type,
                                action_payload_json,
                                interval_minutes,
                                auto_approve,
                                only_when_online,
                                job_id,
                            ),
                        )
                        conn.commit()
                    finally:
                        conn.close()

                    flash("Scheduled job updated.", "success")

            elif form_type == "duplicate_job":
                job_id = _safe_int(request.form.get("job_id"))

                if not job_id:
                    flash("Invalid job id.", "warning")
                else:
                    conn = get_db()
                    try:
                        cur = conn.cursor()
                        job = _fetch_job_by_id(cur, job_id)

                        if not job:
                            flash("Scheduled job not found.", "warning")
                        else:
                            create_scheduled_job(
                                job_name=f"{job['job_name']} (Copy)",
                                description=job["description"] or "",
                                target_type=job["target_type"],
                                target_id=job["target_id"],
                                action_type=job["action_type"],
                                action_payload_json=job["action_payload_json"] or "{}",
                                interval_minutes=job["interval_minutes"] or 60,
                                auto_approve=job["auto_approve"] or 0,
                                only_when_online=job["only_when_online"] or 0,
                            )
                            flash("Scheduled job duplicated.", "success")
                    finally:
                        conn.close()

            elif form_type == "delete_job":
                job_id = _safe_int(request.form.get("job_id"))

                if not job_id:
                    flash("Invalid job id.", "warning")
                else:
                    conn = get_db()
                    try:
                        cur = conn.cursor()
                        cur.execute("DELETE FROM scheduled_job_runs WHERE job_id = ?", (job_id,))
                        cur.execute("DELETE FROM scheduled_jobs WHERE id = ?", (job_id,))
                        conn.commit()
                    finally:
                        conn.close()

                    flash("Scheduled job deleted.", "success")

            elif form_type == "toggle_job":
                job_id = _safe_int(request.form.get("job_id"))
                enabled = request.form.get("enabled") == "1"

                if job_id:
                    set_job_enabled(job_id, enabled)
                    flash(
                        "Scheduled job enabled." if enabled else "Scheduled job disabled.",
                        "success",
                    )
                else:
                    flash("Invalid job id.", "warning")

            elif form_type == "run_job_now":
                job_id = _safe_int(request.form.get("job_id"))

                if job_id:
                    run_job_now(job_id)
                    flash("Scheduled job executed manually.", "success")
                else:
                    flash("Invalid job id.", "warning")

            elif form_type == "tick_scheduler":
                run_due_jobs(limit=50)
                flash("Scheduler tick completed.", "success")

            else:
                flash("Unknown automation action.", "warning")

        except Exception as exc:
            flash(f"Automation action failed: {exc}", "error")

        return redirect(url_for("automation.automation"))

    q = _clean_text(request.args.get("q")).lower()
    status_filter = _clean_text(request.args.get("status"), "all").lower()
    target_filter = _clean_text(request.args.get("target_type"), "all").lower()

    data = _load_automation_data(
        search_text=q,
        status_filter=status_filter,
        target_filter=target_filter,
    )

    return render_template(
        "automation.html",
        machines=data["machines"],
        groups=data["groups"],
        jobs=data["jobs"],
        recent_runs=data["recent_runs"],
        summary=data["summary"],
        search_text=q,
        status_filter=status_filter,
        target_filter=target_filter,
    )


@automation_bp.route("/api/automation/summary")
def automation_summary_api():
    data = _load_automation_data(search_text="", status_filter="all", target_filter="all")
    return jsonify({
        "summary": data["summary"]
    })