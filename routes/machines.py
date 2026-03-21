from flask import Blueprint, render_template, abort

from database import get_db
from services.alert_engine import update_machine_statuses
from services.query_service import get_machine_with_latest_snapshot
from services.runtime_settings import get_runtime_settings
from services.view_model_service import enrich_machine_gpu
from config import MAX_RECENT_SNAPSHOTS


machines_bp = Blueprint("machines", __name__)


@machines_bp.route("/machine/<int:machine_id>")
def machine_detail(machine_id):
    update_machine_statuses()
    runtime_settings = get_runtime_settings()

    conn = get_db()
    try:
        cur = conn.cursor()

        machine_row = get_machine_with_latest_snapshot(cur, machine_id)
        if not machine_row:
            abort(404)

        machine = enrich_machine_gpu(machine_row)
        gpu_list = machine.get("gpu_list", [])

        cur.execute(
            """
            SELECT * FROM snapshots
            WHERE machine_id = ?
            ORDER BY recorded_at DESC, id DESC
            LIMIT ?
            """,
            (machine_id, MAX_RECENT_SNAPSHOTS),
        )
        recent_snapshots = cur.fetchall()

        cur.execute(
            """
            SELECT * FROM drive_snapshots
            WHERE machine_id = ?
            AND recorded_at = (
                SELECT recorded_at
                FROM drive_snapshots
                WHERE machine_id = ?
                ORDER BY recorded_at DESC, id DESC
                LIMIT 1
            )
            ORDER BY mountpoint ASC, device ASC
            """,
            (machine_id, machine_id),
        )
        drive_rows = cur.fetchall()

        cur.execute(
            """
            SELECT * FROM process_snapshots
            WHERE machine_id = ?
            AND recorded_at = (
                SELECT recorded_at
                FROM process_snapshots
                WHERE machine_id = ?
                ORDER BY recorded_at DESC, id DESC
                LIMIT 1
            )
            AND category = 'cpu'
            ORDER BY cpu_percent DESC, memory_mb DESC
            LIMIT ?
            """,
            (machine_id, machine_id, runtime_settings["max_top_processes"]),
        )
        top_cpu_processes = cur.fetchall()

        cur.execute(
            """
            SELECT * FROM process_snapshots
            WHERE machine_id = ?
            AND recorded_at = (
                SELECT recorded_at
                FROM process_snapshots
                WHERE machine_id = ?
                ORDER BY recorded_at DESC, id DESC
                LIMIT 1
            )
            AND category = 'memory'
            ORDER BY memory_mb DESC, memory_percent DESC
            LIMIT ?
            """,
            (machine_id, machine_id, runtime_settings["max_top_processes"]),
        )
        top_memory_processes = cur.fetchall()

        cur.execute(
            """
            SELECT * FROM service_snapshots
            WHERE machine_id = ?
            AND recorded_at = (
                SELECT recorded_at
                FROM service_snapshots
                WHERE machine_id = ?
                ORDER BY recorded_at DESC, id DESC
                LIMIT 1
            )
            ORDER BY status ASC, display_name ASC, service_name ASC
            """,
            (machine_id, machine_id),
        )
        service_rows = cur.fetchall()

        cur.execute(
            """
            SELECT * FROM interface_snapshots
            WHERE machine_id = ?
            AND recorded_at = (
                SELECT recorded_at
                FROM interface_snapshots
                WHERE machine_id = ?
                ORDER BY recorded_at DESC, id DESC
                LIMIT 1
            )
            ORDER BY interface_name ASC
            """,
            (machine_id, machine_id),
        )
        interface_rows = cur.fetchall()

        cur.execute(
            """
            SELECT * FROM inventory_snapshots
            WHERE machine_id = ?
            ORDER BY recorded_at DESC, id DESC
            LIMIT 1
            """,
            (machine_id,),
        )
        inventory_row = cur.fetchone()

        cur.execute(
            """
            SELECT * FROM software_snapshots
            WHERE machine_id = ?
            AND recorded_at = (
                SELECT recorded_at
                FROM software_snapshots
                WHERE machine_id = ?
                ORDER BY recorded_at DESC, id DESC
                LIMIT 1
            )
            ORDER BY name ASC
            LIMIT 300
            """,
            (machine_id, machine_id),
        )
        software_rows = cur.fetchall()

        cur.execute(
            """
            SELECT * FROM alerts
            WHERE machine_id = ?
            AND is_resolved = 0
            ORDER BY recorded_at DESC, id DESC
            """,
            (machine_id,),
        )
        open_alert_rows = cur.fetchall()

        cur.execute(
            """
            SELECT * FROM remote_commands
            WHERE machine_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT 25
            """,
            (machine_id,),
        )
        recent_commands = cur.fetchall()

        snapshots_for_chart = list(reversed(recent_snapshots))

        chart_labels = [
            row["recorded_at"][-8:] if row["recorded_at"] else ""
            for row in snapshots_for_chart
        ]

        cpu_data = [round(row["cpu_percent"] or 0, 2) for row in snapshots_for_chart]
        ram_data = [round(row["ram_percent"] or 0, 2) for row in snapshots_for_chart]

        temp_data = [
            None if row["cpu_temp"] is None else round(row["cpu_temp"], 2)
            for row in snapshots_for_chart
        ]

        up_data = [round(row["net_up_bps"] or 0, 2) for row in snapshots_for_chart]
        down_data = [round(row["net_down_bps"] or 0, 2) for row in snapshots_for_chart]

    finally:
        conn.close()

    return render_template(
        "machine_detail.html",
        machine=machine,
        gpu_list=gpu_list,
        recent_snapshots=recent_snapshots,
        chart_labels=chart_labels,
        cpu_data=cpu_data,
        ram_data=ram_data,
        temp_data=temp_data,
        up_data=up_data,
        down_data=down_data,
        drive_rows=drive_rows,
        top_cpu_processes=top_cpu_processes,
        top_memory_processes=top_memory_processes,
        service_rows=service_rows,
        interface_rows=interface_rows,
        inventory_row=inventory_row,
        software_rows=software_rows,
        open_alert_rows=open_alert_rows,
        recent_commands=recent_commands,
    )