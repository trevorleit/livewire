from __future__ import annotations


TRUTHY_VALUES = {"1", "true", "yes", "on", "enabled"}


def _is_truthy(value) -> bool:
    return str(value or "").strip().lower() in TRUTHY_VALUES


def is_privacy_mode_enabled(settings_map: dict | None) -> bool:
    if not settings_map:
        return False
    return _is_truthy(settings_map.get("privacy_mode_enabled", "0"))


def mask_ip(value: str | None) -> str:
    text = str(value or "").strip()
    if not text:
        return text

    parts = text.split(".")
    if len(parts) == 4 and all(part.isdigit() for part in parts):
        return f"***.***.*.{parts[-1]}"

    if ":" in text:
        pieces = text.split(":")
        if len(pieces) >= 3:
            return ":".join(["****"] * max(1, len(pieces) - 1) + [pieces[-1]])

    return "***"


def mask_hostname(value: str | None) -> str:
    text = str(value or "").strip()
    if not text:
        return text

    if len(text) <= 4:
        return "HOST-****"

    prefix = text[:3].upper()
    return f"{prefix}-******"


def mask_user(value: str | None) -> str:
    text = str(value or "").strip()
    if not text:
        return text
    return "User-****"


def mask_device_id(value: str | None) -> str:
    text = str(value or "").strip()
    if not text:
        return text
    if len(text) <= 4:
        return "ID-****"
    return f"{text[:2]}****{text[-2:]}"


def maybe_mask_ip(value: str | None, enabled: bool) -> str:
    return mask_ip(value) if enabled else str(value or "")


def maybe_mask_hostname(value: str | None, enabled: bool) -> str:
    return mask_hostname(value) if enabled else str(value or "")


def maybe_mask_user(value: str | None, enabled: bool) -> str:
    return mask_user(value) if enabled else str(value or "")


def maybe_mask_device_id(value: str | None, enabled: bool) -> str:
    return mask_device_id(value) if enabled else str(value or "")