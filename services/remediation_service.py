import json
from database import get_db
from services.command_center import create_command

def normalize_rule_payload(action_type, service_name="", pid="", delay_seconds="5"):
    payload = {}
    if action_type == "restart_service":
        payload["service_name"] = (service_name or "").strip()
    elif action_type == "stop_process":
        payload["pid"] = int(pid) if str(pid).strip().isdigit() else None
    elif action_type == "reboot_machine":
        payload["delay_seconds"] = int(delay_seconds) if str(delay_seconds).strip().isdigit() else 5
    return json.dumps(payload)

def create_rule(name, alert_type, role, action, payload, cooldown=30, auto_approve=0):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO remediation_rules (rule_name, alert_type, machine_role, action_type, payload_json, cooldown_minutes, auto_approve, enabled) VALUES (?,?,?,?,?,?,?,1)",
        (name, alert_type, role, action, payload, cooldown, auto_approve)
    )
    conn.commit()
    conn.close()

def set_rule_enabled(rule_id, enabled):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE remediation_rules SET enabled = ? WHERE id = ?", (1 if enabled else 0, rule_id))
    conn.commit()
    conn.close()

def get_rules():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM remediation_rules ORDER BY id DESC")
    rows = cur.fetchall()
    conn.close()
    return rows

def get_recent_runs(limit=50):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM remediation_runs ORDER BY id DESC LIMIT ?", (limit,))
    rows = cur.fetchall()
    conn.close()
    return rows

def run_matching_remediations(machine_id, machine_role, alert_id, alert_type):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM remediation_rules WHERE enabled = 1 AND alert_type = ? AND (machine_role = '' OR machine_role IS NULL OR machine_role = ?) ORDER BY id ASC",
        (alert_type, machine_role or "")
    )
    rules = cur.fetchall()
    for rule in rules:
        create_command(
            machine_id=machine_id,
            action_type=rule["action_type"],
            payload=rule["payload_json"] or "{}",
            requested_by="response_center",
            source="remediation_rule",
            trigger_alert_id=alert_id,
            auto_approve=bool(rule["auto_approve"])
        )
        cur.execute(
            "INSERT INTO remediation_runs (rule_id, machine_id, alert_id, status, action_taken) VALUES (?, ?, ?, ?, ?)",
            (rule["id"], machine_id, alert_id, "queued", f"{rule['action_type']} queued")
        )
    conn.commit()
    conn.close()

# Compatibility wrapper for older alert_engine imports
def run_remediation_rules(machine_id, alert_type, severity=None, message=None, machine_role=None, alert_id=None):
    run_matching_remediations(
        machine_id=machine_id,
        machine_role=machine_role or "",
        alert_id=alert_id,
        alert_type=alert_type,
    )
