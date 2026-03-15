from datetime import datetime, timezone
import json

from flask import Blueprint, request, jsonify

from config import API_KEY
from database import get_db
from services.runtime_settings import get_runtime_settings
from services.alert_engine import (
    evaluate_threshold_alerts,
    evaluate_service_alerts,
    log_event,
)


api_bp = Blueprint("api", __name__)


@api_bp.route("/api/report", methods=["POST"])
def report():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Invalid JSON"}), 400

    if data.get("api_key") != API_KEY:
        return jsonify({"error": "Unauthorized"}), 401

    runtime_settings = get_runtime_settings()
    hostname = data.get("hostname")
    if not hostname:
        return jsonify({"error": "Hostname is required"}), 400

    ip_address = data.get("ip_address")
    os_name = data.get("os_name")
    uptime_seconds = data.get("uptime_seconds", 0)
    cpu_percent = data.get("cpu_percent", 0)
    ram = data.get("ram", {})
    disk = data.get("disk", {})
    network = data.get("network", {})
    current_user = data.get("current_user", "")
    drives = data.get("drives", [])
    processes = data.get("top_processes", {})
    services = data.get("services", [])
    cpu_temp = data.get("cpu_temp")
    interfaces = data.get("interfaces", [])
    inventory = data.get("inventory", {})
    software = data.get("software", [])
    gpu = data.get("gpu", {})
    events = data.get("events", [])
    disk_io = data.get("disk_io", {})
    now = datetime.now(timezone.utc).isoformat()

    conn = get_db()
    try:
        cur = conn.cursor()

        cur.execute("SELECT id FROM machines WHERE hostname = ?", (hostname,))
        machine = cur.fetchone()

        if machine:
            machine_id = machine["id"]
            cur.execute(
                """
                UPDATE machines
                SET ip_address = ?,
                    os_name = ?,
                    last_seen = ?,
                    is_online = 1,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (ip_address, os_name, now, machine_id),
            )
        else:
            cur.execute(
                """
                INSERT INTO machines (
                    hostname,
                    ip_address,
                    os_name,
                    last_seen,
                    is_online
                ) VALUES (?, ?, ?, ?, 1)
                """,
                (hostname, ip_address, os_name, now),
            )
            machine_id = cur.lastrowid
            log_event(
                cur,
                machine_id,
                "machine_registered",
                "info",
                f"{hostname} registered with LiveWire",
                "agent",
            )

        cur.execute(
            """
            INSERT INTO snapshots (
                machine_id,
                cpu_percent,
                ram_total,
                ram_used,
                ram_percent,
                disk_total,
                disk_used,
                disk_percent,
                uptime_seconds,
                current_user,
                net_sent,
                net_recv,
                cpu_temp,
                disk_read_bytes,
                disk_write_bytes,
                net_up_bps,
                net_down_bps,
                gpu_name,
                gpu_load,
                gpu_mem_used_mb,
                gpu_mem_total_mb,
                gpu_temp
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                machine_id,
                cpu_percent,
                ram.get("total", 0),
                ram.get("used", 0),
                ram.get("percent", 0),
                disk.get("total", 0),
                disk.get("used", 0),
                disk.get("percent", 0),
                uptime_seconds,
                current_user,
                network.get("bytes_sent", 0),
                network.get("bytes_recv", 0),
                cpu_temp,
                disk_io.get("read_bytes", 0),
                disk_io.get("write_bytes", 0),
                network.get("up_bps", 0),
                network.get("down_bps", 0),
                gpu.get("name"),
                gpu.get("load_percent"),
                gpu.get("memory_used_mb"),
                gpu.get("memory_total_mb"),
                gpu.get("temperature"),
            ),
        )

        cur.execute(
            "DELETE FROM drive_snapshots WHERE machine_id = ? AND recorded_at < datetime('now', '-14 days')",
            (machine_id,),
        )
        cur.execute(
            "DELETE FROM process_snapshots WHERE machine_id = ? AND recorded_at < datetime('now', '-7 days')",
            (machine_id,),
        )
        cur.execute(
            "DELETE FROM service_snapshots WHERE machine_id = ? AND recorded_at < datetime('now', '-7 days')",
            (machine_id,),
        )
        cur.execute(
            "DELETE FROM interface_snapshots WHERE machine_id = ? AND recorded_at < datetime('now', '-7 days')",
            (machine_id,),
        )
        cur.execute(
            "DELETE FROM inventory_snapshots WHERE machine_id = ? AND recorded_at < datetime('now', '-30 days')",
            (machine_id,),
        )
        cur.execute(
            "DELETE FROM software_snapshots WHERE machine_id = ? AND recorded_at < datetime('now', '-30 days')",
            (machine_id,),
        )
        cur.execute(
            "DELETE FROM event_logs WHERE machine_id = ? AND recorded_at < datetime('now', '-30 days')",
            (machine_id,),
        )

        for drive in drives:
            cur.execute(
                """
                INSERT INTO drive_snapshots (
                    machine_id,
                    recorded_at,
                    device,
                    mountpoint,
                    filesystem,
                    total_bytes,
                    used_bytes,
                    free_bytes,
                    percent_used
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    machine_id,
                    now,
                    drive.get("device"),
                    drive.get("mountpoint"),
                    drive.get("filesystem"),
                    drive.get("total_bytes", 0),
                    drive.get("used_bytes", 0),
                    drive.get("free_bytes", 0),
                    drive.get("percent_used", 0),
                ),
            )

        for category in ("cpu", "memory"):
            for proc in processes.get(category, []):
                cur.execute(
                    """
                    INSERT INTO process_snapshots (
                        machine_id,
                        recorded_at,
                        category,
                        pid,
                        process_name,
                        cpu_percent,
                        memory_percent,
                        memory_mb
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        machine_id,
                        now,
                        category,
                        proc.get("pid"),
                        proc.get("name"),
                        proc.get("cpu_percent", 0),
                        proc.get("memory_percent", 0),
                        proc.get("memory_mb", 0),
                    ),
                )

        for svc in services:
            cur.execute(
                """
                INSERT INTO service_snapshots (
                    machine_id,
                    recorded_at,
                    service_name,
                    display_name,
                    status,
                    start_type,
                    username,
                    binpath
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    machine_id,
                    now,
                    svc.get("service_name"),
                    svc.get("display_name"),
                    svc.get("status"),
                    svc.get("start_type"),
                    svc.get("username"),
                    svc.get("binpath"),
                ),
            )

        for iface in interfaces:
            cur.execute(
                """
                INSERT INTO interface_snapshots (
                    machine_id,
                    recorded_at,
                    interface_name,
                    is_up,
                    speed_mbps,
                    mtu,
                    ip_address,
                    mac_address,
                    bytes_sent,
                    bytes_recv,
                    up_bps,
                    down_bps
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    machine_id,
                    now,
                    iface.get("interface_name"),
                    1 if iface.get("is_up") else 0,
                    iface.get("speed_mbps", 0),
                    iface.get("mtu", 0),
                    iface.get("ip_address"),
                    iface.get("mac_address"),
                    iface.get("bytes_sent", 0),
                    iface.get("bytes_recv", 0),
                    iface.get("up_bps", 0),
                    iface.get("down_bps", 0),
                ),
            )

        if inventory:
            cur.execute(
                """
                INSERT INTO inventory_snapshots (
                    machine_id,
                    recorded_at,
                    cpu_model,
                    physical_cores,
                    logical_cores,
                    total_ram_bytes,
                    boot_time_epoch,
                    python_version,
                    machine_arch,
                    motherboard
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    machine_id,
                    now,
                    inventory.get("cpu_model"),
                    inventory.get("physical_cores"),
                    inventory.get("logical_cores"),
                    inventory.get("total_ram_bytes"),
                    inventory.get("boot_time_epoch"),
                    inventory.get("python_version"),
                    inventory.get("machine_arch"),
                    inventory.get("motherboard"),
                ),
            )

        for pkg in software[:500]:
            cur.execute(
                """
                INSERT INTO software_snapshots (
                    machine_id,
                    recorded_at,
                    source,
                    name,
                    version,
                    publisher,
                    install_date
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    machine_id,
                    now,
                    pkg.get("source"),
                    pkg.get("name"),
                    pkg.get("version"),
                    pkg.get("publisher"),
                    pkg.get("install_date"),
                ),
            )

        for evt in events[:200]:
            log_event(
                cur,
                machine_id,
                evt.get("event_type", "agent_event"),
                evt.get("severity", "info"),
                evt.get("message", ""),
                evt.get("source", "agent"),
                json.dumps(evt),
            )

        evaluate_threshold_alerts(
            cur,
            machine_id,
            hostname,
            cpu_percent,
            ram.get("percent", 0),
            cpu_temp,
            drives,
            runtime_settings,
        )
        evaluate_service_alerts(cur, machine_id, hostname, services)

        conn.commit()
        return jsonify({"status": "ok"})
    finally:
        conn.close()


@api_bp.route("/api/commands/next", methods=["POST"])
def command_next():
    data = request.get_json(silent=True) or {}

    if data.get("api_key") != API_KEY:
        return jsonify({"error": "Unauthorized"}), 401

    hostname = data.get("hostname")
    if not hostname:
        return jsonify({"error": "Hostname required"}), 400

    conn = get_db()
    try:
        cur = conn.cursor()

        cur.execute("SELECT id FROM machines WHERE hostname = ?", (hostname,))
        machine = cur.fetchone()
        if not machine:
            return jsonify({"command": None})

        cur.execute(
            """
            SELECT *
            FROM remote_commands
            WHERE machine_id = ?
              AND status = 'approved'
            ORDER BY approved_at ASC, id ASC
            LIMIT 1
            """,
            (machine["id"],),
        )
        row = cur.fetchone()
        if not row:
            return jsonify({"command": None})

        cur.execute(
            """
            UPDATE remote_commands
            SET status = 'sent',
                created_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (row["id"],),
        )
        conn.commit()

        return jsonify(
            {
                "command": {
                    "id": row["id"],
                    "action_type": row["action_type"],
                    "payload_json": row["payload_json"],
                }
            }
        )
    finally:
        conn.close()


@api_bp.route("/api/commands/result", methods=["POST"])
def command_result():
    data = request.get_json(silent=True) or {}

    if data.get("api_key") != API_KEY:
        return jsonify({"error": "Unauthorized"}), 401

    command_id = data.get("command_id")
    status = data.get("status", "failed")
    output = data.get("output", "")

    conn = get_db()
    try:
        cur = conn.cursor()

        cur.execute(
            "SELECT machine_id, action_type FROM remote_commands WHERE id = ?",
            (command_id,),
        )
        row = cur.fetchone()
        if not row:
            return jsonify({"error": "Command not found"}), 404

        final_status = "completed" if status == "completed" else "failed"

        cur.execute(
            """
            UPDATE remote_commands
            SET status = ?,
                result_text = ?,
                completed_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (final_status, output, command_id),
        )

        log_event(
            cur,
            row["machine_id"],
            "remote_command_result",
            "info" if final_status == "completed" else "warning",
            f"Command {row['action_type']} finished with status {final_status}",
            "agent",
            json.dumps({"command_id": command_id, "output": output[:1500]}),
        )

        conn.commit()
        return jsonify({"status": "ok"})
    finally:
        conn.close()