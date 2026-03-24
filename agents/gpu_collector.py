import json
import shutil
import subprocess
from typing import Any, Dict, List


def _run_powershell(script: str, timeout: int = 8) -> str:
    powershell = shutil.which("powershell") or shutil.which("pwsh")
    if not powershell:
        return ""

    try:
        result = subprocess.run(
            [
                powershell,
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                script,
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            return ""
        return (result.stdout or "").strip()
    except Exception:
        return ""


def _run_powershell_json(script: str, timeout: int = 8) -> Any:
    output = _run_powershell(script, timeout=timeout)
    if not output:
        return None

    try:
        return json.loads(output)
    except Exception:
        return None


def _normalize_adapter_ram_mb(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return round(int(value) / 1024 / 1024, 2)
    except Exception:
        return None


def collect_all_gpus() -> List[Dict[str, Any]]:
    script = r"""
    $gpus = Get-CimInstance Win32_VideoController |
        Select-Object Name, AdapterRAM, DriverVersion, VideoProcessor, PNPDeviceID, Status

    if ($gpus) {
        $gpus | ConvertTo-Json -Compress
    }
    """

    data = _run_powershell_json(script, timeout=10)
    if not data:
        return []

    if isinstance(data, dict):
        data = [data]

    gpus: List[Dict[str, Any]] = []

    for idx, item in enumerate(data):
        name = item.get("Name")
        video_processor = item.get("VideoProcessor")
        vendor_hint = f"{name or ''} {video_processor or ''}".lower()

        vendor = "unknown"
        if any(x in vendor_hint for x in ("nvidia", "geforce", "quadro", "tesla", "rtx", "gtx")):
            vendor = "nvidia"
        elif any(x in vendor_hint for x in ("amd", "radeon", "firepro", "rx ", "vega")):
            vendor = "amd"
        elif any(x in vendor_hint for x in ("intel", "uhd", "iris", "arc")):
            vendor = "intel"

        gpus.append(
            {
                "index": idx,
                "name": name,
                "vendor": vendor,
                "load_percent": None,
                "memory_used_mb": None,
                "memory_total_mb": _normalize_adapter_ram_mb(item.get("AdapterRAM")),
                "temperature": None,
                "driver_version": item.get("DriverVersion"),
                "video_processor": video_processor,
                "pnp_device_id": item.get("PNPDeviceID"),
                "status": item.get("Status"),
            }
        )

    return gpus


def collect_primary_gpu() -> Dict[str, Any]:
    gpus = collect_all_gpus()
    if not gpus:
        return {}

    dedicated_order = {"nvidia": 0, "amd": 1, "intel": 2, "unknown": 3}
    gpus_sorted = sorted(
        gpus,
        key=lambda gpu: (
            dedicated_order.get(gpu.get("vendor", "unknown"), 3),
            0 if (gpu.get("memory_total_mb") or 0) > 0 else 1,
            -(gpu.get("memory_total_mb") or 0),
        ),
    )

    primary = gpus_sorted[0]

    return {
        "name": primary.get("name"),
        "vendor": primary.get("vendor"),
        "load_percent": primary.get("load_percent"),
        "memory_used_mb": primary.get("memory_used_mb"),
        "memory_total_mb": primary.get("memory_total_mb"),
        "temperature": primary.get("temperature"),
    }