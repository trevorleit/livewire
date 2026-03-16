import json

from flask import Blueprint, render_template, request, redirect, url_for, flash

from database import get_db
from services.command_center import create_command, approve_command, cancel_command
from services.alert_engine import update_machine_statuses


actions_bp = Blueprint("actions", __name__)


def _redirect_after_action(machine_id=None):
    target = request.form.get("redirect_to", "actions")
    if target == "machine" and machine_id:
        return redirect(url_for("machines.machine_detail", machine_id=machine_id))
    return redirect(url_for("actions.actions"))


@actions_bp.route("/actions", methods=["GET", "POST"])
def actions():
    if request.method == "POST":
        form_type = request.form.get("form_type", "").strip()

        try:
            if form_type == "create_command":
                machine_id_raw = request.form.get("machine_id", "").strip()
                if not machine_id_raw.isdigit():
                    flash("A valid machine is required.", "warning")
                    return redirect(url_for("actions.actions"))

                machine_id = int(machine_id_raw)
                action_type = request.form.get("action_type", "").strip()
                payload = {}

                if not action_type:
                    flash("Action type is required.", "warning")
                    return _redirect_after_action(machine_id)

                if action_type == "restart_service":
                    service_name = request.form.get("service_name", "").strip()
                    if not service_name:
                        flash("Service name is required for restart_service.", "warning")
                        return _redirect_after_action(machine_id)
                    payload["service_name"] = service_name

                elif action_type == "stop_process":
                    pid = request.form.get("pid", "").strip()
                    if not pid:
                        flash("PID is required for stop_process.", "warning")
                        return _redirect_after_action(machine_id)
                    if not pid.isdigit():
                        flash("PID must be a number.", "warning")
                        return _redirect_after_action(machine_id)
                    payload["pid"] = int(pid)

                elif action_type == "reboot_machine":
                    delay_raw = request.form.get("delay_seconds", "5").strip() or "5"
                    if not delay_raw.isdigit():
                        flash("Delay seconds must be a number.", "warning")
                        return _redirect_after_action(machine_id)
                    payload["delay_seconds"] = int(delay_raw)

                create_command(machine_id, action_type, json.dumps(payload), "dashboard_admin")
                flash("Remote command created.", "success")
                return _redirect_after_action(machine_id)

            elif form_type == "approve_command":
                command_id_raw = request.form.get("command_id", "").strip()
                if not command_id_raw.isdigit():
                    flash("Invalid command id.", "warning")
                    return redirect(url_for("actions.actions"))

                approve_command(int(command_id_raw))
                flash("Command approved.", "success")
                return redirect(url_for("actions.actions"))

            elif form_type == "cancel_command":
                command_id_raw = request.form.get("command_id", "").strip()
                if not command_id_raw.isdigit():
                    flash("Invalid command id.", "warning")
                    return redirect(url_for("actions.actions"))

                cancel_command(int(command_id_raw))
                flash("Command cancelled.", "success")
                return redirect(url_for("actions.actions"))

            else:
                flash("Unknown action request.", "warning")
                return redirect(url_for("actions.actions"))

        except Exception as exc:
            flash(f"Action failed: {exc}", "error")
            machine_id_raw = request.form.get("machine_id", "").strip()
            if machine_id_raw.isdigit():
                return _redirect_after_action(int(machine_id_raw))
            return redirect(url_for("actions.actions"))

    update_machine_statuses()

    conn = get_db()
    try:
        cur = conn.cursor()

        cur.execute(
            """
            SELECT id, hostname, display_name, machine_role, is_online
            FROM machines
            ORDER BY COALESCE(display_name, hostname) ASC
            """
        )
        machines = cur.fetchall()

        cur.execute(
            """
            SELECT
                rc.*,
                COALESCE(m.display_name, m.hostname) AS machine_label,
                sj.job_name AS scheduled_job_name
            FROM remote_commands rc
            JOIN machines m ON m.id = rc.machine_id
            LEFT JOIN scheduled_jobs sj ON sj.id = rc.scheduled_job_id
            ORDER BY rc.created_at DESC, rc.id DESC
            LIMIT 300
            """
        )
        commands = cur.fetchall()

    finally:
        conn.close()

    return render_template("actions.html", machines=machines, commands=commands)