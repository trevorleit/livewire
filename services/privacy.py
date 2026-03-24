from __future__ import annotations

import re


TRUTHY_VALUES = {"1", "true", "yes", "on", "enabled"}


IPV4_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
DOMAIN_USER_RE = re.compile(r"\b[A-Za-z0-9._-]+\\[A-Za-z0-9._-]+\b")

# Device / hostname style examples:
# DESKTOP-ABCD123
# NODE_01
# SERVER-01
# LAPTOP-XYZ9
HOSTNAME_LIKE_RE = re.compile(r"\b[A-Za-z0-9]{3,}[-_][A-Za-z0-9._-]{2,}\b")

# Loose IPv6-ish matcher
IPV6_RE = re.compile(r"\b(?:[0-9a-fA-F]{1,4}:){2,}[0-9a-fA-F]{1,4}\b")


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


def mask_freeform_text(value: str | None) -> str:
    text = str(value or "")
    if not text:
        return text

    text = IPV4_RE.sub(lambda m: mask_ip(m.group(0)), text)
    text = IPV6_RE.sub(lambda m: mask_ip(m.group(0)), text)
    text = DOMAIN_USER_RE.sub("User-****", text)
    text = EMAIL_RE.sub("User-****", text)
    text = HOSTNAME_LIKE_RE.sub(lambda m: mask_hostname(m.group(0)), text)

    return text


def maybe_mask_ip(value: str | None, enabled: bool) -> str:
    return mask_ip(value) if enabled else str(value or "")


def maybe_mask_hostname(value: str | None, enabled: bool) -> str:
    return mask_hostname(value) if enabled else str(value or "")


def maybe_mask_user(value: str | None, enabled: bool) -> str:
    return mask_user(value) if enabled else str(value or "")


def maybe_mask_device_id(value: str | None, enabled: bool) -> str:
    return mask_device_id(value) if enabled else str(value or "")


def maybe_mask_freeform_text(value: str | None, enabled: bool) -> str:
    return mask_freeform_text(value) if enabled else str(value or "")