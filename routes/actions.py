import json
from flask import Blueprint, render_template, request, redirect, url_for
from database import get_db
from services.command_center import create_command, approve_command, cancel_command
from services.alert_engine import update_machine_statuses

actions_bp = Blueprint("actions", __name__)

@actions_bp.route("/actions", methods=["GET", "POST"])
def actions():
    if request.method == "POST":
        form_type = request.form.get("form_type")

        if form_type == "create_command":
            machine_id = int(request.form.get("machine_id"))
            action_type = request.form.get("action_type")
            payload = {}

            if action_type == "restart_service":
                payload["service_name"] = request.form.get("service_name", "").strip()
            elif action_type == "stop_process":
                pid = request.form.get("pid", "").strip()
                if pid:
                    payload["pid"] = int(pid)
            elif action_type == "reboot_machine":
                payload["delay_seconds"] = int(request.form.get("delay_seconds", "5") or 5)

            create_command(machine_id, action_type, json.dumps(payload), "dashboard_admin")

            target = request.form.get("redirect_to", "actions")
            if target == "machine":
                return redirect(url_for("machines.machine_detail", machine_id=machine_id))

        elif form_type == "approve_command":
            approve_command(int(request.form.get("command_id")))

        elif form_type == "cancel_command":
            cancel_command(int(request.form.get("command_id")))

        return redirect(url_for("actions.actions"))

    update_machine_statuses()
    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT id, hostname, display_name, machine_role, is_online FROM machines ORDER BY COALESCE(display_name, hostname) ASC")
    machines = cur.fetchall()

    cur.execute(
        """
        SELECT rc.*, COALESCE(m.display_name, m.hostname) AS machine_label, sj.job_name AS scheduled_job_name
        FROM remote_commands rc
        JOIN machines m ON m.id = rc.machine_id
        LEFT JOIN scheduled_jobs sj ON sj.id = rc.scheduled_job_id
        ORDER BY rc.created_at DESC, rc.id DESC
        LIMIT 300
        """
    )
    commands = cur.fetchall()

    conn.close()
    return render_template("actions.html", machines=machines, commands=commands)