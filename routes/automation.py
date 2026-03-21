from flask import Blueprint, render_template, request, redirect, url_for, flash

from database import get_db
from services.group_service import (
    create_group,
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

        machine_map = {
            row["id"]: (row["display_name"] or row["hostname"])
            for row in machines
        }

        group_map = {
            row["id"]: row["group_name"]
            for row in groups
        }

        job_cards = []
        for job in jobs:
            job_data = dict(job)
            job_data["target_label"] = _build_target_label(job, machine_map, group_map)
            job_cards.append(job_data)

    finally:
        conn.close()

    return render_template(
        "automation.html",
        machines=machines,
        groups=groups,
        jobs=job_cards,
        recent_runs=recent_runs,
    )