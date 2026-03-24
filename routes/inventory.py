from __future__ import annotations

import csv
import io
import json
from typing import Any

from flask import Blueprint, Response, flash, jsonify, redirect, render_template, request, url_for

from database import get_db
from services.helpers import (
    format_last_seen,
    format_rate_bps,
    format_uptime,
    get_runtime_settings,
    mb_to_gb,
    seconds_since,
)


inventory_bp = Blueprint("inventory", __name__)


# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------


def _clean_text(value: Any, fallback: str = "") -> str:
    return str(value or fallback).strip()


def _normalize(value: Any) -> str:
    return _clean_text(value).lower()


def _json_success(**kwargs):
    payload = {"ok": True}
    payload.update(kwargs)
    return jsonify(payload)


def _json_error(message: str, status: int = 400):
    return jsonify({"ok": False, "message": message}), status


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value or 0)
    except Exception:
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value or 0)
    except Exception:
        return default


def _parse_csv_tags(raw: Any) -> list[str]:
    seen = set()
    tags = []
    for part in str(raw or "").split(","):
        tag = part.strip().lower()
        if not tag:
            continue
        if tag in seen:
            continue
        seen.add(tag)
        tags.append(tag)
    return tags


def _machine_matches(
    machine: dict,
    search_text: str = "",
    status_filter: str = "all",
    role_filter: str = "all",
    os_filter: str = "all",
    tag_filter: str = "all",
) -> bool:
    haystack = " ".join(
        [
            str(machine.get("display_name") or ""),
            str(machine.get("hostname") or ""),
            str(machine.get("ip_address") or ""),
            str(machine.get("os_name") or ""),
            str(machine.get("machine_role") or ""),
            str(machine.get("location") or ""),
            str(machine.get("current_user") or ""),
            str(machine.get("notes") or ""),
            " ".join(machine.get("tags") or []),
        ]
    ).lower()

    if search_text and search_text not in haystack:
        return False

    is_online = bool(machine.get("is_online"))
    if status_filter == "online" and not is_online:
        return False
    if status_filter == "offline" and is_online:
        return False

    role_value = _normalize(machine.get("machine_role") or "unassigned")
    if role_filter != "all" and role_value != role_filter:
        return False

    os_value = _normalize(machine.get("os_name") or "unknown")
    if os_filter != "all":
        if os_filter == "windows" and "windows" not in os_value:
            return False
        if os_filter == "linux" and not any(x in os_value for x in ["linux", "ubuntu", "debian"]):
            return False
        if os_filter == "macos" and not any(x in os_value for x in ["mac", "os x"]):
            return False
        if os_filter == "other" and any(
            x in os_value for x in ["windows", "linux", "ubuntu", "debian", "mac", "os x"]
        ):
            return False

    if tag_filter != "all":
        tag_values = [_normalize(t) for t in machine.get("tags") or []]
        if tag_filter not in tag_values:
            return False

    return True


def _table_columns(conn, table_name: str) -> set[str]:
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table_name})")
    return {row[1] for row in cur.fetchall()}


def _ensure_tag_tables(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS machine_tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tag_name TEXT NOT NULL UNIQUE,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS machine_tag_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            machine_id INTEGER NOT NULL,
            tag_id INTEGER NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(machine_id, tag_id),
            FOREIGN KEY(machine_id) REFERENCES machines(id) ON DELETE CASCADE,
            FOREIGN KEY(tag_id) REFERENCES machine_tags(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_machine_tag_links_machine ON machine_tag_links(machine_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_machine_tag_links_tag ON machine_tag_links(tag_id)"
    )
    conn.commit()


def _tag_name_column(conn) -> str:
    columns = _table_columns(conn, "machine_tags")
    for candidate in ["tag_name", "name", "label", "tag", "value"]:
        if candidate in columns:
            return candidate
    return "tag_name"


def _tag_link_machine_column(conn) -> str:
    columns = _table_columns(conn, "machine_tag_links")
    for candidate in ["machine_id", "asset_id"]:
        if candidate in columns:
            return candidate
    return "machine_id"


def _tag_link_tag_column(conn) -> str:
    columns = _table_columns(conn, "machine_tag_links")
    for candidate in ["tag_id", "machine_tag_id"]:
        if candidate in columns:
            return candidate
    return "tag_id"


def _machine_inline_tags_column(conn) -> str | None:
    columns = _table_columns(conn, "machines")
    for candidate in ["tags_json", "tags", "tag_list", "asset_tags", "labels_json", "labels"]:
        if candidate in columns:
            return candidate
    return None


def _parse_maybe_json_tags(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, (list, tuple)):
        return _parse_csv_tags(",".join(str(v) for v in raw))
    text = str(raw).strip()
    if not text:
        return []
    if text.startswith("[") and text.endswith("]"):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return _parse_csv_tags(",".join(str(v) for v in parsed))
        except Exception:
            pass
    return _parse_csv_tags(text)


def _read_inline_tags_from_machine(machine: dict, conn) -> list[str]:
    col = _machine_inline_tags_column(conn)
    if not col:
        return []
    return _parse_maybe_json_tags(machine.get(col))


def _write_inline_tags(conn, machine_id: int, tags: list[str]) -> None:
    col = _machine_inline_tags_column(conn)
    if not col:
        return
    value = json.dumps(tags) if col.endswith("_json") else ", ".join(tags)

    machine_columns = _table_columns(conn, "machines")
    if "updated_at" in machine_columns:
        conn.execute(
            f"UPDATE machines SET {col} = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (value, machine_id),
        )
    else:
        conn.execute(
            f"UPDATE machines SET {col} = ? WHERE id = ?",
            (value, machine_id),
        )


def _get_machine_tags_map(conn) -> dict[int, list[str]]:
    _ensure_tag_tables(conn)
    tag_map: dict[int, list[str]] = {}

    machine_col = _tag_link_machine_column(conn)
    link_tag_col = _tag_link_tag_column(conn)
    tag_col = _tag_name_column(conn)

    try:
        cur = conn.cursor()
        cur.execute(
            f"""
            SELECT l.{machine_col}, t.{tag_col}
            FROM machine_tag_links l
            JOIN machine_tags t ON t.id = l.{link_tag_col}
            ORDER BY t.{tag_col} COLLATE NOCASE ASC
            """
        )
        for row in cur.fetchall():
            machine_id = _safe_int(row[0])
            tag_value = str(row[1] or "").strip()
            if machine_id <= 0 or not tag_value:
                continue
            tag_map.setdefault(machine_id, []).append(tag_value)
    except Exception:
        pass

    inline_col = _machine_inline_tags_column(conn)
    if inline_col:
        cur = conn.cursor()
        cur.execute(f"SELECT id, {inline_col} FROM machines")
        for row in cur.fetchall():
            machine_id = _safe_int(row[0])
            inline_tags = _parse_maybe_json_tags(row[1])
            if machine_id <= 0 or not inline_tags:
                continue
            merged = list(dict.fromkeys((tag_map.get(machine_id) or []) + inline_tags))
            tag_map[machine_id] = merged

    return tag_map


def _get_all_tags(conn) -> list[str]:
    _ensure_tag_tables(conn)
    tag_col = _tag_name_column(conn)
    cur = conn.cursor()
    cur.execute(f"SELECT {tag_col} FROM machine_tags ORDER BY {tag_col} COLLATE NOCASE ASC")
    return [str(row[0]) for row in cur.fetchall() if str(row[0] or "").strip()]


def _set_machine_tags(conn, machine_id: int, tags: list[str]) -> list[str]:
    _ensure_tag_tables(conn)
    tags = _parse_csv_tags(",".join(tags))
    tag_col = _tag_name_column(conn)
    machine_col = _tag_link_machine_column(conn)
    link_tag_col = _tag_link_tag_column(conn)
    cur = conn.cursor()

    try:
        cur.execute(f"DELETE FROM machine_tag_links WHERE {machine_col} = ?", (machine_id,))
        for tag in tags:
            cur.execute(f"INSERT OR IGNORE INTO machine_tags({tag_col}) VALUES (?)", (tag,))
            cur.execute(f"SELECT id FROM machine_tags WHERE {tag_col} = ?", (tag,))
            row = cur.fetchone()
            if not row:
                continue
            cur.execute(
                f"INSERT OR IGNORE INTO machine_tag_links({machine_col}, {link_tag_col}) VALUES (?, ?)",
                (machine_id, _safe_int(row[0])),
            )
    except Exception:
        pass

    _write_inline_tags(conn, machine_id, tags)
    conn.commit()
    return tags


def _apply_tags_mode(existing: list[str], action: str, tag_input: str) -> list[str]:
    incoming = _parse_csv_tags(tag_input)
    existing_set = list(dict.fromkeys(existing))
    if action == "replace_tags":
        return incoming
    if action == "clear_tags":
        return []
    if action == "add_tags":
        return list(dict.fromkeys(existing_set + incoming))
    if action == "remove_tags":
        remove_set = set(incoming)
        return [tag for tag in existing_set if tag not in remove_set]
    return existing_set


def _build_inventory_flags(machine: dict, aging_after_seconds: int) -> list[dict[str, str]]:
    flags: list[dict[str, str]] = []
    is_online = bool(machine.get("is_online"))
    age = seconds_since(machine.get("last_seen"))
    if not is_online:
        flags.append({"label": "Offline", "class": "pill-offline", "pill_class": "pill-offline"})
    elif age is None or age > aging_after_seconds:
        flags.append({"label": "Stale", "class": "pill-warning", "pill_class": "pill-warning"})
    if not _clean_text(machine.get("machine_role")):
        flags.append({"label": "No role", "class": "pill-warning", "pill_class": "pill-warning"})
    if not _clean_text(machine.get("location")):
        flags.append(
            {"label": "No location", "class": "pill-warning", "pill_class": "pill-warning"}
        )
    if not _clean_text(machine.get("notes")):
        flags.append({"label": "No notes", "class": "pill-muted", "pill_class": "pill-muted"})
    if flags:
        flags.insert(0, {"label": "Needs attention", "class": "pill-info", "pill_class": "pill-info"})
    return flags


def _serialize_machine_card(machine: dict, aging_after_seconds: int) -> dict:
    flags = _build_inventory_flags(machine, aging_after_seconds)
    tags = machine.get("tags") or []
    age = seconds_since(machine.get("last_seen"))
    is_stale = bool(machine.get("is_online")) and (age is None or age > aging_after_seconds)
    return {
        "id": machine["id"],
        "display_name": machine.get("display_name") or machine.get("hostname") or f"Machine {machine['id']}",
        "hostname": machine.get("hostname") or "Unknown host",
        "ip_address": machine.get("ip_address") or "No IP",
        "os_name": machine.get("os_name") or "Unknown OS",
        "machine_role": machine.get("machine_role") or "",
        "location": machine.get("location") or "",
        "notes": machine.get("notes") or "",
        "current_user": machine.get("current_user") or "N/A",
        "last_seen": format_last_seen(machine.get("last_seen")),
        "last_seen_label": format_last_seen(machine.get("last_seen")),
        "is_online": bool(machine.get("is_online")),
        "is_stale": bool(is_stale),
        "missing_role": not bool(_clean_text(machine.get("machine_role"))),
        "missing_location": not bool(_clean_text(machine.get("location"))),
        "missing_notes": not bool(_clean_text(machine.get("notes"))),
        "needs_attention": bool(flags),
        "tags": tags,
        "tag_names": tags,
        "flags": flags,
        "inventory_flags": flags,
    }


def _fetch_machine_row(conn, machine_id: int) -> dict | None:
    cur = conn.cursor()
    cur.execute("SELECT * FROM machines WHERE id = ?", (machine_id,))
    row = cur.fetchone()
    if not row:
        return None
    machine = dict(row)
    machine["tags"] = _get_machine_tags_map(conn).get(machine_id, [])
    return machine


def _apply_sort(machines: list[dict], sort_key: str) -> list[dict]:
    if sort_key == "name":
        return sorted(machines, key=lambda x: (x.get("display_name") or "").lower())

    if sort_key == "last_seen_desc":
        return sorted(machines, key=lambda x: x.get("last_seen") or "", reverse=True)

    if sort_key == "last_seen_asc":
        return sorted(machines, key=lambda x: x.get("last_seen") or "")

    if sort_key == "role":
        return sorted(machines, key=lambda x: (x.get("machine_role") or "zzzz").lower())

    if sort_key == "location":
        return sorted(machines, key=lambda x: (x.get("location") or "zzzz").lower())

    if sort_key == "online":
        return sorted(machines, key=lambda x: x.get("is_online"), reverse=True)

    if sort_key == "attention":
        return sorted(machines, key=lambda x: len(x.get("flags") or []), reverse=True)

    return machines


def _group_machines(machines: list[dict], group_by: str) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {}

    for m in machines:
        if group_by == "role":
            key = m.get("machine_role") or "Unassigned"
        elif group_by == "location":
            key = m.get("location") or "Unassigned"
        elif group_by == "status":
            key = "Online" if m.get("is_online") else "Offline"
        else:
            key = "All Machines"

        groups.setdefault(key, []).append(m)

    return groups


def _apply_quick_filter(machines: list[dict], quick_filter: str) -> list[dict]:
    quick_filter = _normalize(quick_filter or "all")
    if quick_filter in {"", "all", "none"}:
        return machines

    if quick_filter == "attention":
        return [m for m in machines if m.get("flags")]
    if quick_filter == "offline":
        return [m for m in machines if not m.get("is_online")]
    if quick_filter == "stale":
        return [m for m in machines if any(flag.get("label") == "Stale" for flag in (m.get("flags") or []))]
    if quick_filter == "missing_role":
        return [m for m in machines if not _clean_text(m.get("machine_role"))]
    if quick_filter == "missing_location":
        return [m for m in machines if not _clean_text(m.get("location"))]
    if quick_filter == "missing_notes":
        return [m for m in machines if not _clean_text(m.get("notes"))]
    if quick_filter == "critical":
        return [m for m in machines if "critical" in [_normalize(t) for t in (m.get("tags") or [])]]

    return machines


def _quick_filter_counts(machines: list[dict]) -> dict[str, int]:
    return {
        "attention": sum(1 for m in machines if m.get("flags")),
        "offline": sum(1 for m in machines if not m.get("is_online")),
        "stale": sum(1 for m in machines if any(flag.get("label") == "Stale" for flag in (m.get("flags") or []))),
        "missing_role": sum(1 for m in machines if not _clean_text(m.get("machine_role"))),
        "missing_location": sum(1 for m in machines if not _clean_text(m.get("location"))),
        "missing_notes": sum(1 for m in machines if not _clean_text(m.get("notes"))),
        "critical": sum(1 for m in machines if "critical" in [_normalize(t) for t in (m.get("tags") or [])]),
    }


# -------------------------------------------------------------------
# Views
# -------------------------------------------------------------------


@inventory_bp.route("/inventory", methods=["GET", "POST"])
def inventory():
    conn = get_db()
    try:
        _ensure_tag_tables(conn)
        cur = conn.cursor()

        if request.method == "POST":
            machine_id = _safe_int(request.form.get("machine_id"))
            if machine_id <= 0:
                flash("Invalid machine selection.", "warning")
                return redirect(url_for("inventory.inventory"))

            machine_columns = _table_columns(conn, "machines")
            role_column = "machine_role" if "machine_role" in machine_columns else "role"

            display_name_value = _clean_text(request.form.get("display_name"))
            role_value = _clean_text(request.form.get("machine_role"))
            location_value = _clean_text(request.form.get("location"))
            notes_value = _clean_text(request.form.get("notes"))

            update_fields = [
                "display_name = ?",
                f"{role_column} = ?",
                "location = ?",
                "notes = ?",
            ]
            update_values = [
                display_name_value,
                role_value,
                location_value,
                notes_value,
            ]

            if "updated_at" in machine_columns:
                update_fields.append("updated_at = CURRENT_TIMESTAMP")

            cur.execute(
                f"""
                UPDATE machines
                SET {", ".join(update_fields)}
                WHERE id = ?
                """,
                (*update_values, machine_id),
            )

            _set_machine_tags(conn, machine_id, _parse_csv_tags(request.form.get("tags")))
            conn.commit()
            flash("Machine inventory details saved.", "success")
            return redirect(url_for("inventory.inventory"))

        settings = get_runtime_settings()
        aging_after_seconds = _safe_int(settings.get("freshness_aging_seconds"), 300) or 300

        search_text = _normalize(request.args.get("q"))
        status_filter = _normalize(request.args.get("status") or "all")
        role_filter = _normalize(request.args.get("role") or "all")
        os_filter = _normalize(request.args.get("os") or "all")
        tag_filter = _normalize(request.args.get("tag") or "all")
        sort = _normalize(request.args.get("sort") or "attention")
        group = _normalize(request.args.get("group") or "none")
        quick = _normalize(request.args.get("quick") or "all")

        cur.execute(
            """
            SELECT *
            FROM machines
            ORDER BY
                CASE WHEN is_online = 1 THEN 0 ELSE 1 END,
                COALESCE(display_name, hostname) COLLATE NOCASE ASC
            """
        )
        machines = [dict(row) for row in cur.fetchall()]
        tag_map = _get_machine_tags_map(conn)

        for machine in machines:
            machine["tags"] = tag_map.get(int(machine["id"]), [])
            machine["flags"] = _build_inventory_flags(machine, aging_after_seconds)

        quick_filter_counts = _quick_filter_counts(machines)

        filtered_machines = [
            machine
            for machine in machines
            if _machine_matches(
                machine,
                search_text=search_text,
                status_filter=status_filter,
                role_filter=role_filter,
                os_filter=os_filter,
                tag_filter=tag_filter,
            )
        ]

        filtered_machines = _apply_quick_filter(filtered_machines, quick)
        filtered_machines = _apply_sort(filtered_machines, sort)
        grouped_machines = _group_machines(filtered_machines, group) if group != "none" else {
            "All Machines": filtered_machines
        }

        total_machines = len(machines)
        visible_machines = len(filtered_machines)
        online_count = sum(1 for m in machines if m.get("is_online"))
        offline_count = total_machines - online_count
        labeled_count = sum(1 for m in machines if _clean_text(m.get("display_name")))
        role_assigned_count = sum(1 for m in machines if _clean_text(m.get("machine_role")))
        location_count = sum(1 for m in machines if _clean_text(m.get("location")))
        notes_count = sum(1 for m in machines if _clean_text(m.get("notes")))
        attention_count = sum(1 for m in machines if m.get("flags"))
        stale_count = sum(
            1 for m in machines if any(flag["label"] == "Stale" for flag in m.get("flags") or [])
        )

        role_options = sorted(
            {_clean_text(m.get("machine_role") or "Unassigned") for m in machines},
            key=lambda x: x.lower(),
        )
        tag_options = _get_all_tags(conn)

        summary = {
            "total_machines": total_machines,
            "visible_machines": visible_machines,
            "online_count": online_count,
            "offline_count": offline_count,
            "labeled_count": labeled_count,
            "role_assigned_count": role_assigned_count,
            "location_count": location_count,
            "notes_count": notes_count,
            "attention_count": attention_count,
            "stale_count": stale_count,
        }
    finally:
        conn.close()

    return render_template(
        "inventory.html",
        machines=filtered_machines,
        grouped_machines=grouped_machines,
        summary=summary,
        role_options=role_options,
        tag_options=tag_options,
        quick_filter_counts=quick_filter_counts,
        search_text=search_text,
        status_filter=status_filter,
        role_filter=role_filter,
        os_filter=os_filter,
        tag_filter=tag_filter,
        sort=sort,
        group=group,
        quick=quick,
        aging_after_seconds=aging_after_seconds,
        format_last_seen=format_last_seen,
    )


@inventory_bp.route("/inventory/export.csv", methods=["GET"])
def export_inventory_csv():
    conn = get_db()
    try:
        _ensure_tag_tables(conn)
        settings = get_runtime_settings()
        aging_after_seconds = _safe_int(settings.get("freshness_aging_seconds"), 300) or 300

        search_text = _normalize(request.args.get("q"))
        status_filter = _normalize(request.args.get("status") or "all")
        role_filter = _normalize(request.args.get("role") or "all")
        os_filter = _normalize(request.args.get("os") or "all")
        tag_filter = _normalize(request.args.get("tag") or "all")
        sort = _normalize(request.args.get("sort") or "attention")
        quick = _normalize(request.args.get("quick") or "all")

        cur = conn.cursor()
        cur.execute(
            """
            SELECT *
            FROM machines
            ORDER BY
                CASE WHEN is_online = 1 THEN 0 ELSE 1 END,
                COALESCE(display_name, hostname) COLLATE NOCASE ASC
            """
        )
        machines = [dict(row) for row in cur.fetchall()]
        tag_map = _get_machine_tags_map(conn)

        for machine in machines:
            machine["tags"] = tag_map.get(int(machine["id"]), [])
            machine["flags"] = _build_inventory_flags(machine, aging_after_seconds)

        filtered_machines = [
            machine
            for machine in machines
            if _machine_matches(
                machine,
                search_text=search_text,
                status_filter=status_filter,
                role_filter=role_filter,
                os_filter=os_filter,
                tag_filter=tag_filter,
            )
        ]
        filtered_machines = _apply_quick_filter(filtered_machines, quick)
        filtered_machines = _apply_sort(filtered_machines, sort)

        output = io.StringIO()
        writer = csv.writer(output)

        writer.writerow(
            [
                "id",
                "display_name",
                "hostname",
                "ip_address",
                "os_name",
                "is_online",
                "last_seen",
                "current_user",
                "machine_role",
                "location",
                "notes",
                "tags",
            ]
        )

        for machine in filtered_machines:
            writer.writerow(
                [
                    machine.get("id"),
                    machine.get("display_name") or "",
                    machine.get("hostname") or "",
                    machine.get("ip_address") or "",
                    machine.get("os_name") or "",
                    "yes" if machine.get("is_online") else "no",
                    machine.get("last_seen") or "",
                    machine.get("current_user") or "",
                    machine.get("machine_role") or "",
                    machine.get("location") or "",
                    machine.get("notes") or "",
                    ", ".join(machine.get("tags") or []),
                ]
            )

        output.seek(0)

        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment; filename=inventory.csv"},
        )
    finally:
        conn.close()


@inventory_bp.route("/inventory/machine/<int:machine_id>/detail", methods=["GET"])
def machine_detail(machine_id: int):
    conn = get_db()
    try:
        machine = _fetch_machine_row(conn, machine_id)
        if not machine:
            return _json_error("Machine not found.", 404)

        settings = get_runtime_settings()
        aging_after_seconds = _safe_int(settings.get("freshness_aging_seconds"), 300) or 300
        flags = _build_inventory_flags(machine, aging_after_seconds)

        cur = conn.cursor()

        alerts_columns = _table_columns(conn, "alerts") if "alerts" in {
            row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        } else set()

        alerts = []
        if alerts_columns:
            alert_time_col = (
                "created_at"
                if "created_at" in alerts_columns
                else ("recorded_at" if "recorded_at" in alerts_columns else None)
            )
            alert_select = ["id", "severity", "alert_type", "message", "status"]
            if alert_time_col:
                alert_select.append(f"{alert_time_col} AS created_at")

            cur.execute(
                f"""
                SELECT {', '.join(alert_select)}
                FROM alerts
                WHERE machine_id = ?
                ORDER BY datetime({alert_time_col or 'CURRENT_TIMESTAMP'}) DESC, id DESC
                LIMIT 5
                """,
                (machine_id,),
            )
            alerts = [dict(row) for row in cur.fetchall()]

        command_columns = _table_columns(conn, "remote_commands") if "remote_commands" in {
            row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        } else set()

        commands = []
        if command_columns:
            command_select = ["id", "action_type", "status", "created_at"]
            if "requested_by" in command_columns:
                command_select.append("requested_by")
            if "completed_at" in command_columns:
                command_select.append("completed_at")
            if "source" in command_columns:
                command_select.append("source")
            if "result_text" in command_columns:
                command_select.append("result_text")

            cur.execute(
                f"""
                SELECT {', '.join(command_select)}
                FROM remote_commands
                WHERE machine_id = ?
                ORDER BY datetime(created_at) DESC, id DESC
                LIMIT 5
                """,
                (machine_id,),
            )
            commands = [dict(row) for row in cur.fetchall()]

        software_columns = _table_columns(conn, "software_snapshots") if "software_snapshots" in {
            row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        } else set()

        software = []
        if software_columns:
            publisher_col = (
                "publisher" if "publisher" in software_columns else ("vendor" if "vendor" in software_columns else None)
            )

            if publisher_col:
                cur.execute(
                    f"""
                    SELECT name, version, {publisher_col} AS publisher, source, install_date, recorded_at
                    FROM software_snapshots
                    WHERE machine_id = ?
                    ORDER BY datetime(recorded_at) DESC, id DESC
                    LIMIT 10
                    """,
                    (machine_id,),
                )
                software = [dict(row) for row in cur.fetchall()]
            else:
                cur.execute(
                    """
                    SELECT name, version, source, install_date, recorded_at
                    FROM software_snapshots
                    WHERE machine_id = ?
                    ORDER BY datetime(recorded_at) DESC, id DESC
                    LIMIT 10
                    """,
                    (machine_id,),
                )
                software = [dict(row) for row in cur.fetchall()]
                for item in software:
                    item["publisher"] = ""

        normalized_alerts = []
        for alert in alerts:
            severity = _normalize(alert.get("severity") or "info")
            status = _normalize(alert.get("status") or "open")
            normalized_alerts.append(
                {
                    "id": alert.get("id"),
                    "alert_type": alert.get("alert_type") or "Alert",
                    "message": alert.get("message") or "",
                    "severity": severity,
                    "severity_label": severity.title(),
                    "status": status,
                    "status_label": "Resolved" if status in {"resolved", "closed"} else status.title(),
                    "recorded_at": alert.get("created_at") or "",
                }
            )

        normalized_commands = []
        for command in commands:
            status = _normalize(command.get("status") or "pending")
            if status in {"approved", "queued", "executing", "running"}:
                status_class = "pill-warning"
            elif status in {"failed", "error", "rejected", "denied"}:
                status_class = "pill-offline"
            elif status in {"completed", "success", "done"}:
                status_class = "pill-online"
            else:
                status_class = "pill-muted"

            normalized_commands.append(
                {
                    "id": command.get("id"),
                    "action_type": command.get("action_type") or "Command",
                    "status": status.title(),
                    "status_class": status_class,
                    "requested_by": command.get("requested_by") or "system",
                    "source": command.get("source") or "dashboard",
                    "created_at": command.get("created_at") or "",
                    "completed_at": command.get("completed_at") or "",
                    "result_text": command.get("result_text") or "",
                }
            )

        gpu_name = machine.get("gpu_name") or ""
        gpu_items = []
        if gpu_name:
            gpu_items.append(
                {
                    "name": gpu_name,
                    "load": round(_safe_float(machine.get("gpu_load")), 1),
                    "temperature": round(_safe_float(machine.get("gpu_temp")), 1),
                    "memory_used_gb": round(mb_to_gb(machine.get("gpu_mem_used_mb")), 2),
                    "memory_total_gb": round(mb_to_gb(machine.get("gpu_mem_total_mb")), 2),
                }
            )

        payload = {
            "machine": {
                "id": machine["id"],
                "display_name": machine.get("display_name") or machine.get("hostname") or f"Machine {machine['id']}",
                "hostname": machine.get("hostname") or "Unknown host",
                "os_name": machine.get("os_name") or "Unknown OS",
                "ip_address": machine.get("ip_address") or "No IP",
                "current_user": machine.get("current_user") or "N/A",
                "location": machine.get("location") or "Unassigned",
                "machine_role": machine.get("machine_role") or "Unassigned",
                "notes": machine.get("notes") or "",
                "last_seen": format_last_seen(machine.get("last_seen")),
                "uptime": format_uptime(machine.get("uptime_seconds")),
                "flags": flags,
                "inventory_flags": flags,
                "is_online": bool(machine.get("is_online")),
                "tags": machine.get("tags") or [],
                "tag_names": machine.get("tags") or [],
            },
            "metrics": {
                "cpu_percent": round(_safe_float(machine.get("cpu_percent")), 1),
                "ram_percent": round(_safe_float(machine.get("ram_percent")), 1),
                "ram_used_gb": round(mb_to_gb(machine.get("ram_used")), 2),
                "ram_total_gb": round(mb_to_gb(machine.get("ram_total")), 2),
                "disk_percent": round(_safe_float(machine.get("disk_percent")), 1),
                "disk_used_gb": round(mb_to_gb(machine.get("disk_used")), 2),
                "disk_total_gb": round(mb_to_gb(machine.get("disk_total")), 2),
                "cpu_temp": round(_safe_float(machine.get("cpu_temp")), 1),
                "net_up": format_rate_bps(machine.get("net_up_bps")),
                "net_down": format_rate_bps(machine.get("net_down_bps")),
            },
            "gpu": {
                "count": len(gpu_items),
                "items": gpu_items,
            },
            "alerts": normalized_alerts,
            "commands": normalized_commands,
            "software": software,
        }
        return jsonify(payload)
    finally:
        conn.close()


@inventory_bp.route("/inventory/machine/<int:machine_id>/notes", methods=["POST"])
def update_machine_notes(machine_id: int):
    conn = get_db()
    try:
        machine = _fetch_machine_row(conn, machine_id)
        if not machine:
            return _json_error("Machine not found.", 404)

        notes = _clean_text((request.get_json(silent=True) or {}).get("notes"))
        machine_columns = _table_columns(conn, "machines")

        if "updated_at" in machine_columns:
            conn.execute(
                "UPDATE machines SET notes = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (notes, machine_id),
            )
        else:
            conn.execute(
                "UPDATE machines SET notes = ? WHERE id = ?",
                (notes, machine_id),
            )

        conn.commit()
        machine["notes"] = notes
        settings = get_runtime_settings()
        aging_after_seconds = _safe_int(settings.get("freshness_aging_seconds"), 300) or 300
        return _json_success(machine=_serialize_machine_card(machine, aging_after_seconds), message="Notes saved.")
    finally:
        conn.close()


@inventory_bp.route("/inventory/machine/<int:machine_id>/tags", methods=["POST"])
def update_machine_tags(machine_id: int):
    conn = get_db()
    try:
        machine = _fetch_machine_row(conn, machine_id)
        if not machine:
            return _json_error("Machine not found.", 404)

        payload = request.get_json(silent=True) or {}
        tags = _parse_csv_tags(payload.get("tags"))
        saved = _set_machine_tags(conn, machine_id, tags)
        machine["tags"] = saved
        settings = get_runtime_settings()
        aging_after_seconds = _safe_int(settings.get("freshness_aging_seconds"), 300) or 300
        return _json_success(machine=_serialize_machine_card(machine, aging_after_seconds), message="Tags saved.")
    finally:
        conn.close()


@inventory_bp.route("/inventory/bulk-update", methods=["POST"])
def bulk_update_inventory():
    conn = get_db()
    try:
        payload = request.get_json(silent=True) or {}
        machine_ids = [mid for mid in [_safe_int(v) for v in payload.get("machine_ids") or []] if mid > 0]
        action = _normalize(payload.get("action"))
        value = _clean_text(payload.get("value"))

        action_aliases = {
            "set_role": "assign_role",
            "update_role": "assign_role",
            "set_location": "assign_location",
            "update_location": "assign_location",
        }
        action = action_aliases.get(action, action)

        if not machine_ids:
            return _json_error("Select at least one machine.")

        if action not in {
            "assign_role",
            "assign_location",
            "replace_notes",
            "append_notes",
            "clear_notes",
            "add_tags",
            "remove_tags",
            "replace_tags",
            "clear_tags",
        }:
            return _json_error("Unsupported bulk action.")

        placeholders = ",".join("?" for _ in machine_ids)
        cur = conn.cursor()
        cur.execute(f"SELECT * FROM machines WHERE id IN ({placeholders})", machine_ids)
        rows = [dict(row) for row in cur.fetchall()]
        if not rows:
            return _json_error("No matching machines were found.", 404)

        machine_columns = _table_columns(conn, "machines")
        role_column = "machine_role" if "machine_role" in machine_columns else "role"

        tag_map = _get_machine_tags_map(conn)
        row_by_id = {int(row["id"]): row for row in rows}

        for machine_id in machine_ids:
            machine = row_by_id.get(machine_id)
            if not machine:
                continue

            if action == "assign_role":
                machine["machine_role"] = value
                if "updated_at" in machine_columns:
                    conn.execute(
                        f"UPDATE machines SET {role_column} = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (value, machine_id),
                    )
                else:
                    conn.execute(
                        f"UPDATE machines SET {role_column} = ? WHERE id = ?",
                        (value, machine_id),
                    )

            elif action == "assign_location":
                machine["location"] = value
                if "updated_at" in machine_columns:
                    conn.execute(
                        "UPDATE machines SET location = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (value, machine_id),
                    )
                else:
                    conn.execute(
                        "UPDATE machines SET location = ? WHERE id = ?",
                        (value, machine_id),
                    )

            elif action == "replace_notes":
                machine["notes"] = value
                if "updated_at" in machine_columns:
                    conn.execute(
                        "UPDATE machines SET notes = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (value, machine_id),
                    )
                else:
                    conn.execute(
                        "UPDATE machines SET notes = ? WHERE id = ?",
                        (value, machine_id),
                    )

            elif action == "append_notes":
                current_notes = _clean_text(machine.get("notes"))
                machine["notes"] = f"{current_notes}\n{value}".strip() if current_notes else value
                if "updated_at" in machine_columns:
                    conn.execute(
                        "UPDATE machines SET notes = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (machine["notes"], machine_id),
                    )
                else:
                    conn.execute(
                        "UPDATE machines SET notes = ? WHERE id = ?",
                        (machine["notes"], machine_id),
                    )

            elif action == "clear_notes":
                machine["notes"] = ""
                if "updated_at" in machine_columns:
                    conn.execute(
                        "UPDATE machines SET notes = '', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (machine_id,),
                    )
                else:
                    conn.execute(
                        "UPDATE machines SET notes = '' WHERE id = ?",
                        (machine_id,),
                    )

            elif action in {"add_tags", "remove_tags", "replace_tags", "clear_tags"}:
                existing_tags = tag_map.get(machine_id, [])
                machine["tags"] = _apply_tags_mode(existing_tags, action, value)
                _set_machine_tags(conn, machine_id, machine["tags"])

        conn.commit()

        settings = get_runtime_settings()
        aging_after_seconds = _safe_int(settings.get("freshness_aging_seconds"), 300) or 300
        updates = [_serialize_machine_card(machine, aging_after_seconds) for machine in rows]

        return _json_success(
            updates=updates,
            machines=updates,
            message=f"Bulk action applied to {len(updates)} machine{'s' if len(updates) != 1 else ''}.",
        )
    finally:
        conn.close()
