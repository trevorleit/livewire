import json

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify

from database import get_db
from services.command_center import create_command, approve_command, cancel_command
from services.alert_engine import update_machine_statuses


actions_bp = Blueprint("actions", __name__)


def _redirect_after_action(machine_id=None):
    target = request.form.get("redirect_to", "actions")
    if target == "machine" and machine_id:
        return redirect(url_for("machines.machine_detail", machine_id=machine_id))
    return redirect(url_for("actions.actions"))


def _clean_text(value, fallback=""):
    return str(value or fallback).strip()


def _safe_json_load(value):
    try:
        return json.loads(value or "{}")
    except Exception:
        return {}


def _action_label(action_type):
    if action_type == "restart_service":
        return "Restart Service"
    if action_type == "stop_process":
        return "Stop Process"
    if action_type == "reboot_machine":
        return "Reboot Machine"
    return action_type or "Unknown"


def _normalize_command(row):
    item = dict(row)
    item["payload"] = _safe_json_load(item.get("action_payload_json"))
    item["status_normalized"] = (item.get("status") or "").lower()
    item["action_label"] = _action_label(item.get("action_type"))
    return item


def _load_action_data(status_filter="all", machine_filter="all"):
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
                m.is_online,
                m.machine_role
            FROM remote_commands rc
            JOIN machines m ON m.id = rc.machine_id
            ORDER BY rc.created_at DESC, rc.id DESC
            LIMIT 300
            """
        )
        raw_commands = cur.fetchall()

    finally:
        conn.close()

    all_commands = [_normalize_command(row) for row in raw_commands]

    filtered_commands = []
    for c in all_commands:
        if status_filter != "all" and c["status_normalized"] != status_filter:
            continue
        if machine_filter != "all" and str(c["machine_id"]) != machine_filter:
            continue
        filtered_commands.append(c)

    pending_commands = []
    active_commands = []
    history_commands = []

    for c in filtered_commands:
        status = c["status_normalized"]
        if status == "pending_approval":
            pending_commands.append(c)
        elif status in ["approved", "sent", "running", "in_progress"]:
            active_commands.append(c)
        else:
            history_commands.append(c)

    completed_count = sum(1 for c in all_commands if c["status_normalized"] in ["completed", "success"])
    failed_count = sum(1 for c in all_commands if c["status_normalized"] in ["failed", "error"])
    cancelled_count = sum(1 for c in all_commands if c["status_normalized"] in ["cancelled", "canceled"])

    summary = {
        "pending": len(pending_commands),
        "active": len(active_commands),
        "history": len(history_commands),
        "total": len(all_commands),
        "completed": completed_count,
        "failed": failed_count,
        "cancelled": cancelled_count,
    }

    return {
        "machines": machines,
        "commands": all_commands,
        "pending_commands": pending_commands,
        "active_commands": active_commands,
        "history_commands": history_commands,
        "summary": summary,
    }


def _serialize_command(c):
    return {
        "id": c.get("id"),
        "machine_id": c.get("machine_id"),
        "machine_label": c.get("machine_label"),
        "machine_role": c.get("machine_role"),
        "is_online": bool(c.get("is_online")),
        "action_type": c.get("action_type"),
        "action_label": c.get("action_label"),
        "status": c.get("status"),
        "status_normalized": c.get("status_normalized"),
        "source": c.get("source") or "dashboard",
        "requested_by": c.get("requested_by") or "unknown",
        "trigger_alert_id": c.get("trigger_alert_id"),
        "created_at": c.get("created_at"),
        "approved_at": c.get("approved_at"),
        "completed_at": c.get("completed_at"),
        "payload": c.get("payload") or {},
        "payload_json": c.get("action_payload_json") or "{}",
        "result_text": c.get("result_text") or "",
    }


@actions_bp.route("/actions", methods=["GET", "POST"])
def actions():
    if request.method == "POST":
        form_type = _clean_text(request.form.get("form_type"))

        try:
            if form_type == "create_command":
                machine_id_raw = _clean_text(request.form.get("machine_id"))

                if not machine_id_raw.isdigit():
                    flash("A valid machine is required.", "warning")
                    return redirect(url_for("actions.actions"))

                machine_id = int(machine_id_raw)
                action_type = _clean_text(request.form.get("action_type"))
                payload = {}

                if not action_type:
                    flash("Action type is required.", "warning")
                    return _redirect_after_action(machine_id)

                if action_type == "restart_service":
                    service_name = _clean_text(request.form.get("service_name"))
                    if not service_name:
                        flash("Service name is required.", "warning")
                        return _redirect_after_action(machine_id)
                    payload["service_name"] = service_name

                elif action_type == "stop_process":
                    pid = _clean_text(request.form.get("pid"))
                    if not pid or not pid.isdigit():
                        flash("Valid PID required.", "warning")
                        return _redirect_after_action(machine_id)
                    payload["pid"] = int(pid)

                elif action_type == "reboot_machine":
                    delay = _clean_text(request.form.get("delay_seconds"), "5")
                    if not delay.isdigit():
                        flash("Delay must be numeric.", "warning")
                        return _redirect_after_action(machine_id)
                    payload["delay_seconds"] = int(delay)

                else:
                    flash("Unsupported action type.", "warning")
                    return _redirect_after_action(machine_id)

                create_command(
                    machine_id,
                    action_type,
                    json.dumps(payload),
                    requested_by="dashboard_admin",
                )

                flash("Command created.", "success")
                return _redirect_after_action(machine_id)

            elif form_type == "approve_command":
                command_id = _clean_text(request.form.get("command_id"))
                if not command_id.isdigit():
                    flash("Invalid command id.", "warning")
                    return redirect(url_for("actions.actions"))

                approve_command(int(command_id))
                flash("Command approved.", "success")
                return redirect(url_for("actions.actions"))

            elif form_type == "cancel_command":
                command_id = _clean_text(request.form.get("command_id"))
                if not command_id.isdigit():
                    flash("Invalid command id.", "warning")
                    return redirect(url_for("actions.actions"))

                cancel_command(int(command_id))
                flash("Command cancelled.", "success")
                return redirect(url_for("actions.actions"))

            else:
                flash("Unknown action request.", "warning")
                return redirect(url_for("actions.actions"))

        except Exception as exc:
            flash(f"Action failed: {exc}", "error")
            return redirect(url_for("actions.actions"))

    update_machine_statuses()

    status_filter = _clean_text(request.args.get("status", "all")).lower()
    machine_filter = _clean_text(request.args.get("machine", "all"))

    data = _load_action_data(status_filter=status_filter, machine_filter=machine_filter)

    return render_template(
        "actions.html",
        machines=data["machines"],
        commands=data["commands"],
        pending_commands=data["pending_commands"],
        active_commands=data["active_commands"],
        history_commands=data["history_commands"],
        summary=data["summary"],
        status_filter=status_filter,
        machine_filter=machine_filter,
    )


@actions_bp.route("/actions/poll")
def actions_poll():
    update_machine_statuses()

    status_filter = _clean_text(request.args.get("status", "all")).lower()
    machine_filter = _clean_text(request.args.get("machine", "all"))

    data = _load_action_data(status_filter=status_filter, machine_filter=machine_filter)

    return jsonify({
        "summary": data["summary"],
        "pending_commands": [_serialize_command(c) for c in data["pending_commands"]],
        "active_commands": [_serialize_command(c) for c in data["active_commands"]],
        "history_commands": [_serialize_command(c) for c in data["history_commands"][:50]],
    })