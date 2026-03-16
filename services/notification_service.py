import requests

from database import insert_notification_log
from services.runtime_settings import fetch_settings, get_bool_setting


def _log(
    channel,
    recipient,
    message,
    status,
    detail="",
    related_alert_id=None,
    related_rule_id=None,
    notification_type="manual",
    subject="",
    conn=None,
):
    details = {}
    if detail:
        details["detail"] = detail

    insert_notification_log(
        notification_type=notification_type,
        channel=channel,
        status=status,
        recipient=recipient,
        subject=subject or None,
        message=message,
        related_alert_id=related_alert_id,
        related_rule_id=related_rule_id,
        details=details or None,
        conn=conn,
    )


def _send(
    subject,
    message,
    related_alert_id=None,
    related_rule_id=None,
    notification_type="manual",
):
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
                _log(
                    channel="discord",
                    recipient=url,
                    message=message,
                    status="sent",
                    detail="",
                    related_alert_id=related_alert_id,
                    related_rule_id=related_rule_id,
                    notification_type=notification_type,
                    subject=subject,
                )
            except Exception as e:
                _log(
                    channel="discord",
                    recipient=url,
                    message=message,
                    status="failed",
                    detail=str(e),
                    related_alert_id=related_alert_id,
                    related_rule_id=related_rule_id,
                    notification_type=notification_type,
                    subject=subject,
                )


def send_test_notification(*_args, **_kwargs):
    _send(
        subject="LiveWire Test Notification",
        message="This is a test notification from LiveWire.",
        notification_type="test",
    )


def notify_alert_opened(machine_label, alert_type, severity, message, related_alert_id=None, related_rule_id=None):
    settings = fetch_settings()
    if not get_bool_setting(settings, "notify_on_alert_open", True):
        return

    _send(
        subject=f"LiveWire Alert Opened: {alert_type}",
        message=f"Machine: {machine_label}\nSeverity: {severity}\nMessage: {message}",
        related_alert_id=related_alert_id,
        related_rule_id=related_rule_id,
        notification_type="alert_opened",
    )


def notify_alert_resolved(machine_label, alert_type, message, related_alert_id=None, related_rule_id=None):
    settings = fetch_settings()
    if not get_bool_setting(settings, "notify_on_alert_resolve", True):
        return

    _send(
        subject=f"LiveWire Alert Resolved: {alert_type}",
        message=f"Machine: {machine_label}\nMessage: {message}",
        related_alert_id=related_alert_id,
        related_rule_id=related_rule_id,
        notification_type="alert_resolved",
    )


def handle_alert_notification(*args, **kwargs):
    machine_label = (
        kwargs.get("machine_label")
        or kwargs.get("hostname")
        or kwargs.get("machine_name")
        or "Unknown Machine"
    )
    alert_type = kwargs.get("alert_type", "unknown_alert")
    severity = kwargs.get("severity", "warning")
    message = kwargs.get("message", "")

    conn = None

    if args:
        positional = list(args)

        # If first positional arg is a DB cursor, keep its connection
        if positional and hasattr(positional[0], "execute"):
            try:
                conn = positional[0].connection
            except Exception:
                conn = None
            positional = positional[1:]

        if len(positional) >= 1 and not kwargs.get("machine_label"):
            machine_label = positional[0]
        if len(positional) >= 2 and not kwargs.get("alert_type"):
            alert_type = positional[1]
        if len(positional) >= 3 and not kwargs.get("severity"):
            severity = positional[2]
        if len(positional) >= 4 and not kwargs.get("message"):
            message = positional[3]

    event_type = kwargs.get("event_type", "opened")
    related_alert_id = kwargs.get("related_alert_id")
    related_rule_id = kwargs.get("related_rule_id")

    if event_type == "resolved":
        notify_alert_resolved(
            machine_label=machine_label,
            alert_type=alert_type,
            message=message,
            related_alert_id=related_alert_id,
            related_rule_id=related_rule_id,
        )
        _log(
            channel="system",
            recipient=machine_label,
            message=message,
            status="sent",
            detail="",
            related_alert_id=related_alert_id,
            related_rule_id=related_rule_id,
            notification_type="alert_resolved",
            subject=f"LiveWire Alert Resolved: {alert_type}",
            conn=conn,
        )
        return

    notify_alert_opened(
        machine_label=machine_label,
        alert_type=alert_type,
        severity=severity,
        message=message,
        related_alert_id=related_alert_id,
        related_rule_id=related_rule_id,
    )
    _log(
        channel="system",
        recipient=machine_label,
        message=message,
        status="sent",
        detail="",
        related_alert_id=related_alert_id,
        related_rule_id=related_rule_id,
        notification_type="alert_opened",
        subject=f"LiveWire Alert Opened: {alert_type}",
        conn=conn,
    )


def handle_resolved_alert_notification(*args, **kwargs):
    kwargs["event_type"] = "resolved"
    return handle_alert_notification(*args, **kwargs)