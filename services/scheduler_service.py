import json
from datetime import datetime, UTC, timedelta

from database import get_db


def utc_now_sql():
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")


def normalize_payload(action_type, service_name="", pid="", delay_seconds="5"):
    payload = {}

    if action_type == "restart_service":
        payload["service_name"] = (service_name or "").strip()
    elif action_type == "stop_process":
        payload["pid"] = int(pid) if str(pid).strip().isdigit() else None
    elif action_type == "reboot_machine":
        payload["delay_seconds"] = int(delay_seconds) if str(delay_seconds).strip().isdigit() else 5

    payload = {k: v for k, v in payload.items() if v is not None}
    return json.dumps(payload)


def create_scheduled_job(
    job_name,
    description,
    target_type,
    target_id,
    action_type,
    action_payload_json,
    interval_minutes,
    auto_approve=0,
    only_when_online=0,
):
    conn = get_db()
    try:
        cur = conn.cursor()
        next_run = utc_now_sql()

        cur.execute(
            """
            INSERT INTO scheduled_jobs (
                job_name,
                description,
                target_type,
                target_id,
                action_type,
                action_payload_json,
                interval_minutes,
                auto_approve,
                only_when_online,
                enabled,
                next_run_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
            """,
            (
                (job_name or "").strip(),
                (description or "").strip(),
                target_type,
                target_id,
                action_type,
                action_payload_json,
                int(interval_minutes or 60),
                1 if auto_approve else 0,
                1 if only_when_online else 0,
                next_run,
            ),
        )

        conn.commit()
    finally:
        conn.close()


def set_job_enabled(job_id, enabled):
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE scheduled_jobs SET enabled = ? WHERE id = ?",
            (1 if enabled else 0, job_id),
        )
        conn.commit()
    finally:
        conn.close()


def queue_remote_command(
    cur,
    machine_id,
    action_type,
    action_payload_json,
    source="scheduler",
    approval_status="pending_approval",
):
    try:
        cur.execute(
            """
            INSERT INTO remote_commands (
                machine_id,
                action_type,
                action_payload_json,
                status,
                source,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, datetime('now'))
            """,
            (machine_id, action_type, action_payload_json, approval_status, source),
        )
    except Exception:
        cur.execute(
            """
            INSERT INTO remote_commands (
                machine_id,
                action_type,
                action_payload_json,
                status,
                created_at
            )
            VALUES (?, ?, ?, ?, datetime('now'))
            """,
            (machine_id, action_type, action_payload_json, approval_status),
        )


def expand_target_machines(cur, target_type, target_id):
    if target_type == "machine":
        cur.execute("SELECT id, is_online FROM machines WHERE id = ?", (target_id,))
        row = cur.fetchone()
        return [row] if row else []

    if target_type == "group":
        cur.execute(
            """
            SELECT m.id, m.is_online
            FROM machine_group_members mgm
            JOIN machines m ON m.id = mgm.machine_id
            WHERE mgm.group_id = ?
            """,
            (target_id,),
        )
        return cur.fetchall()

    return []


def record_run(cur, job_id, status, summary_text):
    cur.execute(
        """
        INSERT INTO scheduled_job_runs (job_id, status, summary_text, created_at)
        VALUES (?, ?, ?, datetime('now'))
        """,
        (job_id, status, summary_text),
    )


def run_job_now(job_id):
    conn = get_db()
    try:
        cur = conn.cursor()

        cur.execute("SELECT * FROM scheduled_jobs WHERE id = ?", (job_id,))
        job = cur.fetchone()
        if not job:
            return

        approval_status = "approved" if job["auto_approve"] else "pending_approval"
        machines = expand_target_machines(cur, job["target_type"], job["target_id"])

        queued = 0
        skipped = 0

        for machine in machines:
            if job["only_when_online"] and not machine["is_online"]:
                skipped += 1
                continue

            queue_remote_command(
                cur,
                machine["id"],
                job["action_type"],
                job["action_payload_json"],
                "scheduler_manual",
                approval_status,
            )
            queued += 1

        record_run(cur, job_id, "success", f"Queued {queued} command(s), skipped {skipped}.")
        conn.commit()
    finally:
        conn.close()


def run_due_jobs(limit=50):
    conn = get_db()
    try:
        cur = conn.cursor()

        try:
            cur.execute(
                """
                SELECT *
                FROM scheduled_jobs
                WHERE enabled = 1
                  AND next_run_at IS NOT NULL
                  AND next_run_at <= datetime('now')
                ORDER BY next_run_at ASC
                LIMIT ?
                """,
                (limit,),
            )
            jobs = cur.fetchall()
        except Exception:
            return

        for job in jobs:
            approval_status = "approved" if job["auto_approve"] else "pending_approval"
            machines = expand_target_machines(cur, job["target_type"], job["target_id"])

            queued = 0
            skipped = 0

            for machine in machines:
                if job["only_when_online"] and not machine["is_online"]:
                    skipped += 1
                    continue

                queue_remote_command(
                    cur,
                    machine["id"],
                    job["action_type"],
                    job["action_payload_json"],
                    "scheduler",
                    approval_status,
                )
                queued += 1

            next_run = datetime.now(UTC) + timedelta(minutes=int(job["interval_minutes"] or 60))
            cur.execute(
                """
                UPDATE scheduled_jobs
                SET last_run_at = datetime('now'),
                    next_run_at = ?
                WHERE id = ?
                """,
                (next_run.strftime("%Y-%m-%d %H:%M:%S"), job["id"]),
            )

            record_run(cur, job["id"], "success", f"Queued {queued} command(s), skipped {skipped}.")

        conn.commit()
    finally:
        conn.close()


def get_scheduler_overview(cur=None):
    """
    Supports both:
      get_scheduler_overview()
      get_scheduler_overview(cur)
    so older dashboard code keeps working.
    """
    close_conn = False

    if cur is None:
        conn = get_db()
        cur = conn.cursor()
        close_conn = True
    else:
        conn = None

    overview = {
        "enabled_jobs": 0,
        "disabled_jobs": 0,
        "due_now": 0,
        "total_groups": 0,
        "recent_runs": [],
        "jobs": [],
    }

    try:
        cur.execute("SELECT COUNT(*) AS c FROM machine_groups")
        row = cur.fetchone()
        overview["total_groups"] = row["c"] if row else 0

        cur.execute("SELECT COUNT(*) AS c FROM scheduled_jobs WHERE enabled = 1")
        row = cur.fetchone()
        overview["enabled_jobs"] = row["c"] if row else 0

        cur.execute("SELECT COUNT(*) AS c FROM scheduled_jobs WHERE enabled = 0")
        row = cur.fetchone()
        overview["disabled_jobs"] = row["c"] if row else 0

        cur.execute(
            """
            SELECT COUNT(*) AS c
            FROM scheduled_jobs
            WHERE enabled = 1
              AND next_run_at IS NOT NULL
              AND next_run_at <= datetime('now')
            """
        )
        row = cur.fetchone()
        overview["due_now"] = row["c"] if row else 0

        cur.execute(
            """
            SELECT *
            FROM scheduled_jobs
            ORDER BY enabled DESC, next_run_at ASC, id DESC
            LIMIT 10
            """
        )
        overview["jobs"] = cur.fetchall()

        cur.execute(
            """
            SELECT r.*, j.job_name
            FROM scheduled_job_runs r
            LEFT JOIN scheduled_jobs j ON j.id = r.job_id
            ORDER BY r.created_at DESC, r.id DESC
            LIMIT 10
            """
        )
        overview["recent_runs"] = cur.fetchall()
    except Exception:
        pass
    finally:
        if close_conn and conn is not None:
            conn.close()

    return overview