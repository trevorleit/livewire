def get_machine_with_latest_snapshot(cur, machine_id):
    cur.execute(
        """
        SELECT
            m.*,

            s.recorded_at,
            s.cpu_percent,
            s.ram_total,
            s.ram_used,
            s.ram_percent,
            s.disk_total,
            s.disk_used,
            s.disk_percent,
            s.uptime_seconds,
            s.current_user,
            s.net_sent,
            s.net_recv,
            s.net_up_bps,
            s.net_down_bps,
            s.cpu_temp,
            s.disk_read_bytes,
            s.disk_write_bytes,
            s.gpu_name,
            s.gpu_load,
            s.gpu_mem_used_mb,
            s.gpu_mem_total_mb,
            s.gpu_temp,
            s.gpu_json,

            (
                SELECT COUNT(*)
                FROM alerts a
                WHERE a.machine_id = m.id
                  AND a.is_resolved = 0
            ) AS open_alert_count,

            (
                SELECT GROUP_CONCAT(g.group_name, ', ')
                FROM machine_group_members gm
                JOIN machine_groups g ON g.id = gm.group_id
                WHERE gm.machine_id = m.id
            ) AS group_names

        FROM machines m
        LEFT JOIN snapshots s
            ON s.id = (
                SELECT id
                FROM snapshots
                WHERE machine_id = m.id
                ORDER BY recorded_at DESC, id DESC
                LIMIT 1
            )
        WHERE m.id = ?
        """,
        (machine_id,),
    )
    return cur.fetchone()


def get_dashboard_machines(cur):
    cur.execute(
        """
        SELECT
            m.*,

            s.recorded_at,
            s.cpu_percent,
            s.ram_percent,
            s.disk_percent,
            s.uptime_seconds,
            s.current_user,
            s.cpu_temp,
            s.net_up_bps,
            s.net_down_bps,
            s.gpu_name,
            s.gpu_load,
            s.gpu_mem_used_mb,
            s.gpu_mem_total_mb,
            s.gpu_temp,
            s.gpu_json,

            (
                SELECT COUNT(*)
                FROM alerts a
                WHERE a.machine_id = m.id
                  AND a.is_resolved = 0
            ) AS open_alert_count,

            (
                SELECT GROUP_CONCAT(g.group_name, ', ')
                FROM machine_group_members gm
                JOIN machine_groups g ON g.id = gm.group_id
                WHERE gm.machine_id = m.id
            ) AS group_names

        FROM machines m
        LEFT JOIN snapshots s
            ON s.id = (
                SELECT id
                FROM snapshots
                WHERE machine_id = m.id
                ORDER BY recorded_at DESC, id DESC
                LIMIT 1
            )
        ORDER BY COALESCE(m.display_name, m.hostname) ASC
        """
    )
    return cur.fetchall()


def get_open_alert_count(cur):
    cur.execute("SELECT COUNT(*) AS total FROM alerts WHERE is_resolved = 0")
    row = cur.fetchone()
    return row["total"] if row else 0