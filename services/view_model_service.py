import json
from typing import Any, Dict, List, Optional


def _safe_dict(row: Any) -> Dict[str, Any]:
    if row is None:
        return {}
    if isinstance(row, dict):
        return dict(row)
    try:
        return dict(row)
    except Exception:
        return {}


def _safe_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _safe_number(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except Exception:
        return None


def _parse_gpu_json(gpu_json: Any) -> List[Dict[str, Any]]:
    if not gpu_json:
        return []

    try:
        parsed = json.loads(gpu_json)
    except Exception:
        return []

    if isinstance(parsed, dict):
        return [parsed]

    if isinstance(parsed, list):
        return [item for item in parsed if isinstance(item, dict)]

    return []


def _normalize_gpu(gpu: Dict[str, Any], default_source: str = "agent") -> Dict[str, Any]:
    return {
        "index": gpu.get("index"),
        "name": _safe_str(gpu.get("name")),
        "vendor": _safe_str(gpu.get("vendor")),
        "source": _safe_str(gpu.get("source")) or default_source,
        "load_percent": _safe_number(gpu.get("load_percent")),
        "memory_used_mb": _safe_number(gpu.get("memory_used_mb")),
        "memory_total_mb": _safe_number(gpu.get("memory_total_mb")),
        "temperature": _safe_number(gpu.get("temperature")),
        "driver_version": _safe_str(gpu.get("driver_version")),
        "uuid": _safe_str(gpu.get("uuid")),
        "video_processor": _safe_str(gpu.get("video_processor")),
        "pnp_device_id": _safe_str(gpu.get("pnp_device_id")),
        "status": _safe_str(gpu.get("status")),
    }


def _build_legacy_gpu(machine: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not machine.get("gpu_name"):
        return []

    return [
        _normalize_gpu(
            {
                "index": 0,
                "name": machine.get("gpu_name"),
                "load_percent": machine.get("gpu_load"),
                "memory_used_mb": machine.get("gpu_mem_used_mb"),
                "memory_total_mb": machine.get("gpu_mem_total_mb"),
                "temperature": machine.get("gpu_temp"),
                "vendor": None,
                "source": "legacy",
            },
            default_source="legacy",
        )
    ]


def enrich_machine_gpu(row: Any) -> Dict[str, Any]:
    machine = _safe_dict(row)

    parsed_gpu_list = _parse_gpu_json(machine.get("gpu_json"))
    gpu_list = [_normalize_gpu(gpu) for gpu in parsed_gpu_list if isinstance(gpu, dict)]

    if not gpu_list:
        gpu_list = _build_legacy_gpu(machine)

    for idx, gpu in enumerate(gpu_list):
        if gpu.get("index") is None:
            gpu["index"] = idx

    primary_gpu: Dict[str, Any] = gpu_list[0] if gpu_list else {}

    machine["gpu_list"] = gpu_list
    machine["gpu_count"] = len(gpu_list)

    machine["primary_gpu_name"] = primary_gpu.get("name")
    machine["primary_gpu_load"] = primary_gpu.get("load_percent")
    machine["primary_gpu_temp"] = primary_gpu.get("temperature")
    machine["primary_gpu_mem_used"] = primary_gpu.get("memory_used_mb")
    machine["primary_gpu_mem_total"] = primary_gpu.get("memory_total_mb")
    machine["primary_gpu_vendor"] = primary_gpu.get("vendor")
    machine["primary_gpu_source"] = primary_gpu.get("source")
    machine["primary_gpu_driver_version"] = primary_gpu.get("driver_version")

    return machine


def enrich_machine_list_gpu(rows: List[Any]) -> List[Dict[str, Any]]:
    return [enrich_machine_gpu(row) for row in rows]