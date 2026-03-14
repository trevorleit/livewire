import requests
from database import get_db
from services.runtime_settings import fetch_settings, get_bool_setting


def _log(channel, dest, msg, status, detail=""):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO notification_logs (channel_type, destination, message, status, detail) VALUES (?,?,?,?,?)",
        (channel, dest, msg, status, detail),
    )
    conn.commit()
    conn.close()


def _send(subject, message):
    settings = fetch_settings()

    if get_bool_setting(settings, "notifications_enable_discord", False):
        url = settings.get("discord_webhook_url", "").strip()
        if url:
            try:
                response = requests.post(
                    url,
                    json={"content": f"**{subject}**\n{message}"},
                    timeout=10,
                )
                response.raise_for_status()
                _log("discord", url, message, "sent", "")
            except Exception as e:
                _log("discord", url, message, "failed", str(e))


def send_test_notification():
    _send("LiveWire Test Notification", "This is a test notification from LiveWire.")


def notify_alert_opened(machine_label, alert_type, severity, message):
    settings = fetch_settings()
    if not get_bool_setting(settings, "notify_on_alert_open", True):
        return

    _send(
        f"LiveWire Alert Opened: {alert_type}",
        f"Machine: {machine_label}\nSeverity: {severity}\nMessage: {message}",
    )


def notify_alert_resolved(machine_label, alert_type, message):
    settings = fetch_settings()
    if not get_bool_setting(settings, "notify_on_alert_resolve", True):
        return

    _send(
        f"LiveWire Alert Resolved: {alert_type}",
        f"Machine: {machine_label}\nMessage: {message}",
    )


def handle_alert_notification(*args, **kwargs):
    """
    Compatibility wrapper for older and newer alert_engine calls.

    Supports both positional and keyword styles, including:
    - alert_id
    - machine_id
    - machine_label
    - hostname
    - alert_type
    - severity
    - message
    """
    machine_label = (
        kwargs.get("machine_label")
        or kwargs.get("hostname")
        or kwargs.get("machine_name")
        or "Unknown Machine"
    )
    alert_type = kwargs.get("alert_type", "unknown_alert")
    severity = kwargs.get("severity", "warning")
    message = kwargs.get("message", "")

    if args:
        if len(args) >= 1 and not kwargs.get("machine_label"):
            machine_label = args[0]
        if len(args) >= 2 and not kwargs.get("alert_type"):
            alert_type = args[1]
        if len(args) >= 3 and not kwargs.get("severity"):
            severity = args[2]
        if len(args) >= 4 and not kwargs.get("message"):
            message = args[3]

    notify_alert_opened(machine_label, alert_type, severity, message)


def handle_resolved_alert_notification(*args, **kwargs):
    """
    Compatibility wrapper for resolved alerts.
    """
    machine_label = (
        kwargs.get("machine_label")
        or kwargs.get("hostname")
        or kwargs.get("machine_name")
        or "Unknown Machine"
    )
    alert_type = kwargs.get("alert_type", "unknown_alert")
    message = kwargs.get("message", "")

    if args:
        if len(args) >= 1 and not kwargs.get("machine_label"):
            machine_label = args[0]
        if len(args) >= 2 and not kwargs.get("alert_type"):
            alert_type = args[1]
        if len(args) >= 3 and not kwargs.get("message"):
            message = args[2]

    notify_alert_resolved(machine_label, alert_type, message)
