import json

from database import (
    get_db,
    insert_remediation_rule,
    list_remediation_rules,
    set_remediation_rule_enabled,
)
from services.command_center import create_command


def normalize_rule_payload(action_type, service_name="", pid="", delay_seconds="5"):
    payload = {}

    if action_type == "restart_service":
        payload["service_name"] = (service_name or "").strip()
    elif action_type == "stop_process":
        payload["pid"] = int(pid) if str(pid).strip().isdigit() else None
    elif action_type == "reboot_machine":
        payload["delay_seconds"] = int(delay_seconds) if str(delay_seconds).strip().isdigit() else 5

    payload = {k: v for k, v in payload.items() if v is not None}
    return json.dumps(payload)


def create_rule(name, alert_type, role, action, payload, cooldown=30, auto_approve=0):
    try:
        action_payload = json.loads(payload) if payload else {}
    except Exception:
        action_payload = {}

    return insert_remediation_rule(
        name=name,
        trigger_type=(alert_type or "").strip(),
        action_type=(action or "").strip(),
        machine_role=(role or "").strip() or None,
        cooldown_seconds=int(cooldown) if str(cooldown).strip().isdigit() else 30,
        action_payload=action_payload,
        auto_approve=1 if auto_approve else 0,
        enabled=1,
    )


def set_rule_enabled(rule_id, enabled):
    set_remediation_rule_enabled(rule_id=rule_id, enabled=enabled)


def get_rules():
    return list_remediation_rules()


def get_recent_runs(limit=50):
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT *
            FROM remediation_runs
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        )
        return cur.fetchall()
    finally:
        conn.close()


def run_matching_remediations(machine_id, machine_role, related_alert_id, alert_type):
    conn = get_db()
    try:
        cur = conn.cursor()

        cur.execute(
            """
            SELECT
                id,
                name,
                description,
                enabled,
                machine_role,
                trigger_type,
                severity,
                metric_name,
                comparison_operator,
                threshold_value,
                cooldown_seconds,
                action_type,
                action_payload_json,
                auto_approve,
                created_at,
                updated_at
            FROM remediation_rules
            WHERE enabled = 1
              AND trigger_type = ?
              AND (
                    machine_role IS NULL
                    OR machine_role = ''
                    OR machine_role = ?
                  )
            ORDER BY id ASC
            """,
            (alert_type, machine_role or ""),
        )
        rules = cur.fetchall()

        for rule in rules:
            try:
                action_payload = json.loads(rule["action_payload_json"] or "{}")
            except Exception:
                action_payload = {}

            status = "approved" if bool(rule["auto_approve"]) else "pending_approval"

            command_id = create_command(
                machine_id=machine_id,
                action_type=rule["action_type"],
                payload=json.dumps(action_payload),
                requested_by="response_center",
                status=status,
                source="remediation_rule",
                trigger_alert_id=related_alert_id,
            )

            cur.execute(
                """
                INSERT INTO remediation_runs (
                    related_rule_id,
                    machine_id,
                    related_alert_id,
                    command_id,
                    status,
                    message
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    rule["id"],
                    machine_id,
                    related_alert_id,
                    command_id,
                    "queued",
                    f"{rule['action_type']} queued",
                ),
            )

        conn.commit()
    finally:
        conn.close()


def run_remediation_rules(*args, **kwargs):
    positional_machine_id = None

    if args:
        if hasattr(args[0], "execute"):
            if len(args) > 1:
                positional_machine_id = args[1]
        else:
            positional_machine_id = args[0]

    machine_id = kwargs.get("machine_id", positional_machine_id)
    machine_role = kwargs.get("machine_role", "")
    related_alert_id = kwargs.get("related_alert_id")
    alert_type = kwargs.get("alert_type")

    if machine_id is None or not alert_type:
        return

    run_matching_remediations(
        machine_id=machine_id,
        machine_role=machine_role or "",
        related_alert_id=related_alert_id,
        alert_type=alert_type,
    )