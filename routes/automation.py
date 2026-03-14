from flask import Blueprint, render_template, request, redirect, url_for
from database import get_db
from services.group_service import create_group, add_machine_to_group, remove_machine_from_group, fetch_groups_with_members
from services.scheduler_service import create_scheduled_job, set_job_enabled, normalize_payload, run_due_jobs, run_job_now

automation_bp = Blueprint("automation", __name__)

@automation_bp.route("/automation", methods=["GET","POST"])
def automation():
    if request.method == "POST":
        form_type = request.form.get("form_type")

        if form_type == "create_group":
            create_group(
                request.form.get("group_name",""),
                request.form.get("description",""),
                request.form.get("color_hex","#60a5fa")
            )

        elif form_type == "add_group_member":
            add_machine_to_group(int(request.form.get("group_id")), int(request.form.get("machine_id")))

        elif form_type == "remove_group_member":
            remove_machine_from_group(int(request.form.get("group_id")), int(request.form.get("machine_id")))

        elif form_type == "create_job":
            action_type = request.form.get("action_type")
            payload_json = normalize_payload(
                action_type,
                service_name=request.form.get("service_name",""),
                pid=request.form.get("pid",""),
                delay_seconds=request.form.get("delay_seconds","5")
            )
            create_scheduled_job(
                request.form.get("job_name",""),
                request.form.get("description",""),
                request.form.get("target_type","machine"),
                int(request.form.get("target_id")),
                action_type,
                payload_json,
                int(request.form.get("interval_minutes","60") or 60),
                auto_approve = 1 if request.form.get("auto_approve")=="on" else 0,
                only_when_online = 1 if request.form.get("only_when_online")=="on" else 0
            )

        elif form_type == "toggle_job":
            set_job_enabled(int(request.form.get("job_id")), request.form.get("enabled")=="1")

        elif form_type == "run_job_now":
            run_job_now(int(request.form.get("job_id")))

        elif form_type == "tick_scheduler":
            run_due_jobs(limit=50)

        return redirect(url_for("automation.automation"))

    run_due_jobs(limit=50)

    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT id, hostname, display_name, is_online, machine_role FROM machines ORDER BY COALESCE(display_name, hostname) ASC")
    machines = cur.fetchall()

    groups = fetch_groups_with_members(cur)

    cur.execute("SELECT * FROM scheduled_jobs ORDER BY id DESC")
    jobs = cur.fetchall()

    cur.execute("SELECT * FROM scheduled_job_runs ORDER BY id DESC LIMIT 40")
    recent_runs = cur.fetchall()

    conn.close()

    return render_template(
        "automation.html",
        machines=machines,
        groups=groups,
        jobs=jobs,
        recent_runs=recent_runs
    )