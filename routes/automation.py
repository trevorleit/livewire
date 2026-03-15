from flask import Blueprint, render_template, request, redirect, url_for

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

    return f"{target_type} #{target_id}"


@automation_bp.route("/automation", methods=["GET", "POST"])
def automation():
    if request.method == "POST":
        form_type = request.form.get("form_type", "")

        if form_type == "create_group":
            create_group(
                request.form.get("group_name", ""),
                request.form.get("description", ""),
                request.form.get("color_hex", "#60a5fa"),
            )

        elif form_type == "add_group_member":
            group_id = request.form.get("group_id")
            machine_id = request.form.get("machine_id")

            if str(group_id).isdigit() and str(machine_id).isdigit():
                add_machine_to_group(int(group_id), int(machine_id))

        elif form_type == "remove_group_member":
            group_id = request.form.get("group_id")
            machine_id = request.form.get("machine_id")

            if str(group_id).isdigit() and str(machine_id).isdigit():
                remove_machine_from_group(int(group_id), int(machine_id))

        elif form_type == "create_job":
            action_type = request.form.get("action_type", "").strip()
            target_type = request.form.get("target_type", "machine").strip()
            target_id = request.form.get("target_id")

            if action_type and target_type in ("machine", "group") and str(target_id).isdigit():
                action_payload_json = normalize_payload(
                    action_type,
                    service_name=request.form.get("service_name", ""),
                    pid=request.form.get("pid", ""),
                    delay_seconds=request.form.get("delay_seconds", "5"),
                )

                create_scheduled_job(
                    request.form.get("job_name", ""),
                    request.form.get("description", ""),
                    target_type,
                    int(target_id),
                    action_type,
                    action_payload_json,
                    int(request.form.get("interval_minutes", "60") or 60),
                    auto_approve=1 if request.form.get("auto_approve") == "on" else 0,
                    only_when_online=1 if request.form.get("only_when_online") == "on" else 0,
                )

        elif form_type == "toggle_job":
            job_id = request.form.get("job_id")
            enabled = request.form.get("enabled") == "1"

            if str(job_id).isdigit():
                set_job_enabled(int(job_id), enabled)

        elif form_type == "run_job_now":
            job_id = request.form.get("job_id")

            if str(job_id).isdigit():
                run_job_now(int(job_id))

        elif form_type == "tick_scheduler":
            run_due_jobs(limit=50)

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