import os
import re
import sys

# Add project root before importing project modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import getpass
import json
import platform
import shutil
import socket
import subprocess
import time
import winreg
import zipfile
from typing import Any, Dict, List, Optional, Tuple

import psutil
import requests

from services.service_name_utils import candidate_service_names, normalize_service_label


# -------------------------------------------------------------------
# Agent configuration
# -------------------------------------------------------------------

SERVER_URL = "http://127.0.0.1:5000"
API_KEY = "livewire-dev-key"
INTERVAL = 30
TOP_PROCESS_LIMIT = 8
SOFTWARE_LIMIT = 300
WATCH_SERVICES = ["Apache", "MySQL", "Spooler"]

# Dynamic runtime-controlled sensor source
LHM_JSON_URL: Optional[str] = None

_previous_net_totals = None
_previous_interface_totals: Dict[str, Dict[str, float]] = {}


# -------------------------------------------------------------------
# API helpers
# -------------------------------------------------------------------

def api_post(path: str, payload: Dict[str, Any], timeout: int = 30):
    return requests.post(f"{SERVER_URL}{path}", json=payload, timeout=timeout)


def fetch_runtime_settings() -> Dict[str, Any]:
    try:
        resp = requests.get(f"{SERVER_URL}/api/settings", timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


# -------------------------------------------------------------------
# LibreHardwareMonitor management
# -------------------------------------------------------------------

def _clean_setting_text(value: Any, fallback: str = "") -> str:
    return str(value or fallback).strip().strip('"').strip("'")


def _run_command(args: List[str], timeout: int = 15) -> Tuple[bool, str]:
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
        )
        output = ((result.stdout or "") + "\n" + (result.stderr or "")).strip()
        return result.returncode == 0, output
    except Exception as exc:
        return False, str(exc)


def is_lhm_running(url: str) -> bool:
    try:
        resp = requests.get(url, timeout=2)
        return resp.status_code == 200
    except Exception:
        return False


def ensure_lhm_installed(settings: Dict[str, Any]) -> None:
    install_dir = _clean_setting_text(settings.get("lhm_install_dir"))
    download_url = _clean_setting_text(settings.get("lhm_download_url"))

    if not install_dir:
        return

    exe_path = os.path.join(install_dir, "LibreHardwareMonitor.exe")
    if os.path.exists(exe_path):
        return

    if not settings.get("lhm_auto_install"):
        print("LHM not installed and auto-install is disabled")
        return

    if not download_url:
        print("LHM auto-install enabled, but no download URL is configured")
        return

    try:
        print("Downloading LibreHardwareMonitor...")
        os.makedirs(install_dir, exist_ok=True)

        zip_path = os.path.join(install_dir, "lhm.zip")

        response = requests.get(download_url, timeout=60)
        response.raise_for_status()

        with open(zip_path, "wb") as f:
            f.write(response.content)

        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            zip_ref.extractall(install_dir)

        try:
            os.remove(zip_path)
        except Exception:
            pass

        print("LibreHardwareMonitor installed successfully")
    except Exception as exc:
        print(f"LHM install failed: {exc}")


def ensure_lhm_scheduled_task(
    exe_path: str,
    task_name: str = "LiveWire-LibreHardwareMonitor",
) -> bool:
    query_ok, _ = _run_command(["schtasks", "/query", "/tn", task_name], timeout=10)
    if query_ok:
        return True

    create_ok, create_output = _run_command(
        [
            "schtasks",
            "/create",
            "/tn",
            task_name,
            "/tr",
            exe_path,
            "/sc",
            "ONLOGON",
            "/rl",
            "HIGHEST",
            "/f",
        ],
        timeout=20,
    )

    if not create_ok:
        print(f"Failed to create LHM scheduled task: {create_output}")
        return False

    return True


def run_lhm_scheduled_task(task_name: str = "LiveWire-LibreHardwareMonitor") -> bool:
    run_ok, run_output = _run_command(
        ["schtasks", "/run", "/tn", task_name],
        timeout=10,
    )
    if not run_ok:
        print(f"Failed to run LHM scheduled task: {run_output}")
        return False
    return True


def ensure_lhm_running(settings: Dict[str, Any]) -> None:
    global LHM_JSON_URL

    if not settings.get("enhanced_hwmon_enabled"):
        LHM_JSON_URL = None
        return

    url = _clean_setting_text(settings.get("lhm_url"))
    install_dir = _clean_setting_text(settings.get("lhm_install_dir"))

    if not url:
        LHM_JSON_URL = None
        return

    LHM_JSON_URL = url

    if is_lhm_running(url):
        return

    if not settings.get("lhm_auto_start"):
        print("LHM not running and auto-start is disabled")
        return

    exe_path = os.path.join(install_dir, "LibreHardwareMonitor.exe")
    if not os.path.exists(exe_path):
        print("LHM auto-start requested, but executable was not found")
        return

    task_name = "LiveWire-LibreHardwareMonitor"

    if not ensure_lhm_scheduled_task(exe_path, task_name=task_name):
        return

    print("Starting LibreHardwareMonitor via scheduled task...")
    if not run_lhm_scheduled_task(task_name=task_name):
        return

    for _ in range(6):
        time.sleep(2)
        if is_lhm_running(url):
            print("LibreHardwareMonitor is running")
            return

    print("LibreHardwareMonitor scheduled task ran, but sensor endpoint is still unavailable")


# -------------------------------------------------------------------
# Basic system helpers
# -------------------------------------------------------------------

def get_ip() -> str:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        sock.close()
        return ip
    except Exception:
        return "unknown"


def get_hostname() -> str:
    return socket.gethostname()


def get_os_name() -> str:
    return f"{platform.system()} {platform.release()}"


def get_uptime_seconds() -> int:
    return int(time.time() - psutil.boot_time())


# -------------------------------------------------------------------
# Disk helpers
# -------------------------------------------------------------------

def get_primary_disk_usage():
    try:
        if platform.system().lower() == "windows":
            return psutil.disk_usage("C:\\")
        return psutil.disk_usage("/")
    except Exception:
        return None


def get_all_drives() -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    seen_mounts = set()

    for part in psutil.disk_partitions(all=False):
        if not part.mountpoint or part.mountpoint in seen_mounts:
            continue

        seen_mounts.add(part.mountpoint)

        if "cdrom" in (part.opts or "").lower():
            continue

        try:
            usage = psutil.disk_usage(part.mountpoint)
        except Exception:
            continue

        results.append(
            {
                "device": part.device,
                "mountpoint": part.mountpoint,
                "filesystem": part.fstype,
                "total_bytes": usage.total,
                "used_bytes": usage.used,
                "free_bytes": usage.free,
                "percent_used": usage.percent,
            }
        )

    return results


def get_disk_io() -> Dict[str, int]:
    diskio = psutil.disk_io_counters()
    return {
        "read_bytes": diskio.read_bytes if diskio else 0,
        "write_bytes": diskio.write_bytes if diskio else 0,
    }


# -------------------------------------------------------------------
# Process helpers
# -------------------------------------------------------------------

def warm_process_cpu() -> None:
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            proc.cpu_percent(None)
        except Exception:
            pass
    time.sleep(0.15)


def get_top_processes(limit: int = TOP_PROCESS_LIMIT) -> Dict[str, List[Dict[str, Any]]]:
    warm_process_cpu()
    rows: List[Dict[str, Any]] = []

    for proc in psutil.process_iter(["pid", "name", "memory_percent", "memory_info"]):
        try:
            info = proc.info
            memory_info = info.get("memory_info")
            rows.append(
                {
                    "pid": info.get("pid"),
                    "name": info.get("name") or "unknown",
                    "cpu_percent": proc.cpu_percent(None),
                    "memory_percent": info.get("memory_percent") or 0,
                    "memory_mb": round((memory_info.rss if memory_info else 0) / (1024 ** 2), 2),
                }
            )
        except Exception:
            pass

    return {
        "cpu": sorted(rows, key=lambda x: (x["cpu_percent"], x["memory_mb"]), reverse=True)[:limit],
        "memory": sorted(rows, key=lambda x: (x["memory_mb"], x["memory_percent"]), reverse=True)[:limit],
    }


# -------------------------------------------------------------------
# Temperature helpers
# -------------------------------------------------------------------

def get_cpu_temperature() -> Optional[float]:
    try:
        temps = psutil.sensors_temperatures()
    except Exception:
        return None

    if not temps:
        return None

    for key in ["coretemp", "k10temp", "cpu_thermal", "acpitz"] + list(temps.keys()):
        vals = [e.current for e in temps.get(key, []) if getattr(e, "current", None) is not None]
        if vals:
            return round(max(vals), 2)

    return None


# -------------------------------------------------------------------
# Service helpers
# -------------------------------------------------------------------

def _get_windows_service_catalog() -> List[Dict[str, Any]]:
    try:
        return [svc.as_dict() for svc in psutil.win_service_iter()]
    except Exception:
        return []


def _resolve_service_info(requested_name: str, catalog: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    candidates = [normalize_service_label(v) for v in candidate_service_names(requested_name)]
    if not candidates:
        return None

    for info in catalog:
        service_name = normalize_service_label(info.get("name"))
        display_name = normalize_service_label(info.get("display_name"))
        if service_name in candidates or display_name in candidates:
            return info

    return None


def get_watched_services() -> List[Dict[str, Any]]:
    if platform.system().lower() != "windows":
        return []

    results: List[Dict[str, Any]] = []
    catalog = _get_windows_service_catalog()

    for service_name in WATCH_SERVICES:
        info = _resolve_service_info(service_name, catalog)

        if info:
            results.append(
                {
                    "service_name": info.get("name"),
                    "display_name": info.get("display_name") or info.get("name"),
                    "status": info.get("status"),
                    "start_type": info.get("start_type"),
                    "username": info.get("username"),
                    "binpath": info.get("binpath"),
                    "requested_name": service_name,
                }
            )
        else:
            results.append(
                {
                    "service_name": service_name,
                    "display_name": service_name,
                    "status": "not_found",
                    "start_type": "",
                    "username": "",
                    "binpath": "",
                    "requested_name": service_name,
                }
            )

    return results


# -------------------------------------------------------------------
# Network helpers
# -------------------------------------------------------------------

def get_network_totals() -> Dict[str, float]:
    global _previous_net_totals

    counters = psutil.net_io_counters()
    now = time.time()
    current = {
        "time": now,
        "sent": counters.bytes_sent,
        "recv": counters.bytes_recv,
    }

    up_bps = 0.0
    down_bps = 0.0

    if _previous_net_totals:
        elapsed = max(now - _previous_net_totals["time"], 0.001)
        up_bps = max((current["sent"] - _previous_net_totals["sent"]) / elapsed, 0)
        down_bps = max((current["recv"] - _previous_net_totals["recv"]) / elapsed, 0)

    _previous_net_totals = current

    return {
        "bytes_sent": counters.bytes_sent,
        "bytes_recv": counters.bytes_recv,
        "up_bps": up_bps,
        "down_bps": down_bps,
    }


def get_interfaces() -> List[Dict[str, Any]]:
    global _previous_interface_totals

    results: List[Dict[str, Any]] = []
    stats = psutil.net_if_stats()
    addrs = psutil.net_if_addrs()
    io = psutil.net_io_counters(pernic=True)
    now = time.time()

    for name, stat in stats.items():
        iface_addrs = addrs.get(name, [])
        ip_address = None
        mac_address = None

        for addr in iface_addrs:
            fam = str(addr.family)
            if "AF_LINK" in fam or fam.endswith("17"):
                mac_address = addr.address
            elif "AF_INET" in fam or fam.endswith("2"):
                if not ip_address:
                    ip_address = addr.address

        nic_io = io.get(name)
        bytes_sent = nic_io.bytes_sent if nic_io else 0
        bytes_recv = nic_io.bytes_recv if nic_io else 0
        up_bps = 0.0
        down_bps = 0.0

        prev = _previous_interface_totals.get(name)
        if prev:
            elapsed = max(now - prev["time"], 0.001)
            up_bps = max((bytes_sent - prev["bytes_sent"]) / elapsed, 0)
            down_bps = max((bytes_recv - prev["bytes_recv"]) / elapsed, 0)

        _previous_interface_totals[name] = {
            "time": now,
            "bytes_sent": bytes_sent,
            "bytes_recv": bytes_recv,
        }

        results.append(
            {
                "interface_name": name,
                "is_up": bool(stat.isup),
                "speed_mbps": stat.speed,
                "mtu": stat.mtu,
                "ip_address": ip_address,
                "mac_address": mac_address,
                "bytes_sent": bytes_sent,
                "bytes_recv": bytes_recv,
                "up_bps": up_bps,
                "down_bps": down_bps,
            }
        )

    return results


# -------------------------------------------------------------------
# Inventory helpers
# -------------------------------------------------------------------

def get_inventory() -> Dict[str, Any]:
    vm = psutil.virtual_memory()
    return {
        "cpu_model": platform.processor() or "Unknown CPU",
        "physical_cores": psutil.cpu_count(logical=False),
        "logical_cores": psutil.cpu_count(logical=True),
        "total_ram_bytes": vm.total,
        "boot_time_epoch": psutil.boot_time(),
        "python_version": sys.version.split()[0],
        "machine_arch": platform.machine(),
        "motherboard": None,
    }


# -------------------------------------------------------------------
# GPU helpers
# -------------------------------------------------------------------

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


def _normalize_adapter_ram_mb(value: Any) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        return round(int(value) / 1024 / 1024, 2)
    except Exception:
        return None


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None or value == "" or str(value).strip().lower() in {"n/a", "na", "none"}:
            return None
        return float(value)
    except Exception:
        return None


def detect_gpu_vendor(name: Optional[str], video_processor: Optional[str]) -> str:
    vendor_hint = f"{name or ''} {video_processor or ''}".lower()

    if any(x in vendor_hint for x in ("nvidia", "geforce", "quadro", "tesla", "rtx", "gtx")):
        return "nvidia"
    if any(x in vendor_hint for x in ("amd", "radeon", "firepro", "rx ", "vega")):
        return "amd"
    if any(x in vendor_hint for x in ("intel", "uhd", "iris", "arc")):
        return "intel"
    return "unknown"


def is_virtual_gpu_name(name: Optional[str]) -> bool:
    text = (name or "").lower()
    virtual_terms = [
        "meta virtual monitor",
        "virtual",
        "basic render",
        "microsoft basic display",
        "remote display",
        "indirect display",
        "parsec virtual",
    ]
    return any(term in text for term in virtual_terms)


def is_integrated_gpu_name(name: Optional[str]) -> bool:
    text = (name or "").lower()
    integrated_terms = [
        "intel uhd",
        "intel iris",
        "intel hd",
        "radeon(tm) graphics",
        "vega 8",
        "vega 7",
        "apu",
    ]
    return any(term in text for term in integrated_terms)


def get_nvidia_gpus() -> List[Dict[str, Any]]:
    """
    Accurate NVIDIA telemetry from nvidia-smi.
    """
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=index,uuid,name,utilization.gpu,memory.used,memory.total,temperature.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=8,
        )

        if result.returncode != 0 or not result.stdout.strip():
            return []

        gpus: List[Dict[str, Any]] = []

        for line in result.stdout.strip().splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 7:
                continue

            try:
                gpu_index = int(parts[0])
            except Exception:
                gpu_index = len(gpus)

            gpus.append(
                {
                    "index": gpu_index,
                    "uuid": parts[1],
                    "name": parts[2],
                    "vendor": "nvidia",
                    "load_percent": _safe_float(parts[3]),
                    "memory_used_mb": _safe_float(parts[4]),
                    "memory_total_mb": _safe_float(parts[5]),
                    "temperature": _safe_float(parts[6]),
                    "driver_version": None,
                    "video_processor": parts[2],
                    "pnp_device_id": None,
                    "status": "OK",
                    "source": "nvidia-smi",
                }
            )

        return gpus
    except Exception:
        return []


def get_nvidia_gpu_list_fallback() -> List[Dict[str, Any]]:
    """
    Inventory-only NVIDIA fallback using `nvidia-smi -L`.
    Useful when detailed query output is incomplete but card listing works.
    """
    try:
        result = subprocess.run(
            ["nvidia-smi", "-L"],
            capture_output=True,
            text=True,
            timeout=5,
        )

        if result.returncode != 0 or not result.stdout.strip():
            return []

        gpus: List[Dict[str, Any]] = []

        for idx, line in enumerate(result.stdout.strip().splitlines()):
            gpus.append(
                {
                    "index": idx,
                    "uuid": None,
                    "name": line.strip(),
                    "vendor": "nvidia",
                    "load_percent": None,
                    "memory_used_mb": None,
                    "memory_total_mb": None,
                    "temperature": None,
                    "driver_version": None,
                    "video_processor": line.strip(),
                    "pnp_device_id": None,
                    "status": "OK",
                    "source": "nvidia-smi-list",
                }
            )

        return gpus
    except Exception:
        return []


def _extract_first_number(text: Optional[str]) -> Optional[float]:
    """
    Generic scalar parser for percentages, temps, etc.
    Do not rely on this for memory strings like '16,384 MB' or '8.0 GB'.
    """
    if text is None:
        return None

    raw = str(text).strip()
    if not raw:
        return None

    match = re.search(r"-?\d+(?:[.,]\d+)?", raw)
    if not match:
        return None

    number_text = match.group(0).replace(",", ".")
    try:
        return float(number_text)
    except Exception:
        return None


def _extract_memory_mb(text: Optional[str]) -> Optional[float]:
    """
    Parse memory strings from LibreHardwareMonitor and normalize to MB.

    Examples:
    - '16384 MB'
    - '16,384 MB'
    - '8.0 GB'
    - '15.9 GiB'
    - '24576 MiB'
    """
    if text is None:
        return None

    raw = str(text).strip()
    if not raw:
        return None

    upper = raw.upper()
    match = re.search(r"(-?\d[\d,\.]*)\s*([KMGTP]I?B)?", upper)
    if not match:
        return None

    number_text = match.group(1).strip()
    unit = (match.group(2) or "MB").strip()

    if "," in number_text and "." in number_text:
        number_text = number_text.replace(",", "")
    elif "," in number_text:
        parts = number_text.split(",")
        if len(parts[-1]) == 3 and all(p.isdigit() for p in parts):
            number_text = "".join(parts)
        else:
            number_text = number_text.replace(",", ".")

    try:
        value = float(number_text)
    except Exception:
        return None

    unit_multipliers = {
        "KB": 1 / 1024,
        "KIB": 1 / 1024,
        "MB": 1,
        "MIB": 1,
        "GB": 1024,
        "GIB": 1024,
        "TB": 1024 * 1024,
        "TIB": 1024 * 1024,
    }

    multiplier = unit_multipliers.get(unit, 1)
    return round(value * multiplier, 2)


def _sanitize_gpu_memory_total(vendor: Optional[str], total_mb: Optional[float]) -> Optional[float]:
    if total_mb is None:
        return None

    vendor_text = (vendor or "").lower()

    if total_mb <= 0:
        return None

    # AMD LHM sometimes exposes shared/system/aggregate memory totals that are not true VRAM.
    # Reject obviously inflated totals to avoid polluting snapshots/UI.
    if vendor_text == "amd" and total_mb > 24576:
        return None

    return round(total_mb, 2)


def _is_preferred_vram_total_label(label: str) -> bool:
    label = (label or "").lower().strip()

    preferred_terms = [
        "dedicated memory total",
        "gpu memory total",
        "vram total",
        "memory size",
        "frame buffer size",
    ]
    return any(term == label or term in label for term in preferred_terms)


def _is_rejected_vram_total_label(label: str) -> bool:
    label = (label or "").lower().strip()

    rejected_terms = [
        "local memory total",
        "shared memory",
        "shared gpu memory",
        "shared gpu memory total",
        "adapter memory",
        "graphics memory total",
        "total available memory",
    ]

    if label == "memory total":
        return True

    return any(term in label for term in rejected_terms)


def _is_vram_used_label(label: str) -> bool:
    label = (label or "").lower().strip()

    used_terms = [
        "memory used",
        "gpu memory used",
        "d3d dedicated memory used",
        "dedicated memory used",
        "local memory used",
        "vram used",
    ]
    return any(term in label for term in used_terms)


def _fetch_lhm_data() -> Optional[Any]:
    if not LHM_JSON_URL:
        return None

    try:
        resp = requests.get(LHM_JSON_URL, timeout=3)
        if resp.status_code != 200:
            return None
        return resp.json()
    except Exception:
        return None


def _is_real_gpu_name(name: Optional[str]) -> bool:
    text = (name or "").strip().lower()
    if not text:
        return False

    generic_sensor_names = {
        "gpu core",
        "gpu soc",
        "gpu memory",
        "gpu package",
        "gpu hotspot",
        "gpu hot spot",
        "gpu fan",
        "gpu #1",
        "gpu #2",
        "gpu temperature",
        "gpu load",
        "gpu clock",
        "gpu memory clock",
        "gpu shader",
        "gpu shader clock",
        "gpu bus",
        "gpu voltage",
        "fan",
        "hot spot",
        "package",
        "memory",
        "core",
        "soc",
    }
    if text in generic_sensor_names:
        return False

    real_gpu_tokens = [
        "radeon",
        "geforce",
        "quadro",
        "tesla",
        "rtx",
        "gtx",
        "rx ",
        "arc ",
        "arc a",
        "arc b",
        "intel arc",
    ]
    return any(token in text for token in real_gpu_tokens)


def _walk_lhm_gpu_tree(
    node: Any,
    gpu_map: Dict[str, Dict[str, Any]],
    current_gpu_name: Optional[str] = None,
) -> None:
    if not isinstance(node, dict):
        if isinstance(node, list):
            for item in node:
                _walk_lhm_gpu_tree(item, gpu_map, current_gpu_name)
        return

    node_name = str(node.get("Text") or node.get("Name") or "").strip()
    node_type = str(node.get("Type") or "").strip().lower()
    node_value = node.get("Value")

    active_gpu_name = current_gpu_name

    if _is_real_gpu_name(node_name):
        active_gpu_name = node_name

        if active_gpu_name not in gpu_map:
            gpu_map[active_gpu_name] = {
                "index": len(gpu_map),
                "uuid": None,
                "name": active_gpu_name,
                "vendor": detect_gpu_vendor(active_gpu_name, active_gpu_name),
                "load_percent": None,
                "memory_used_mb": None,
                "memory_total_mb": None,
                "temperature": None,
                "driver_version": None,
                "video_processor": active_gpu_name,
                "pnp_device_id": None,
                "status": "OK",
                "source": "lhm",
            }

    if active_gpu_name and active_gpu_name in gpu_map:
        gpu = gpu_map[active_gpu_name]
        label = node_name.lower()
        sensor_text = node_value if node_value is not None else node_name

        scalar_number = _extract_first_number(sensor_text)
        memory_mb = _extract_memory_mb(sensor_text)

        if scalar_number is not None:
            if node_type == "temperature" or "temp" in label or "hot spot" in label or "hotspot" in label:
                current_temp = gpu.get("temperature")
                gpu["temperature"] = scalar_number if current_temp is None else max(current_temp, scalar_number)

            elif node_type == "load" or "load" in label:
                if (
                    "gpu core" in label
                    or label == "gpu core"
                    or label == "gpu"
                    or "core load" in label
                    or "d3d" in label
                    or "graphics" in label
                ):
                    gpu["load_percent"] = scalar_number

        if memory_mb is not None and (node_type in {"smalldata", "data"} or "memory" in label or "vram" in label):
            if _is_vram_used_label(label):
                current_used = gpu.get("memory_used_mb")
                gpu["memory_used_mb"] = memory_mb if current_used is None else max(current_used, memory_mb)

            elif _is_preferred_vram_total_label(label) and not _is_rejected_vram_total_label(label):
                sanitized_total = _sanitize_gpu_memory_total(gpu.get("vendor"), memory_mb)
                if sanitized_total is not None:
                    current_total = gpu.get("memory_total_mb")
                    gpu["memory_total_mb"] = (
                        sanitized_total if current_total is None else max(current_total, sanitized_total)
                    )

    children = node.get("Children")
    if isinstance(children, list):
        for child in children:
            _walk_lhm_gpu_tree(child, gpu_map, active_gpu_name)


def get_lhm_gpus() -> List[Dict[str, Any]]:
    if platform.system().lower() != "windows":
        return []

    data = _fetch_lhm_data()
    if not data:
        return []

    gpu_map: Dict[str, Dict[str, Any]] = {}
    _walk_lhm_gpu_tree(data, gpu_map)

    results = list(gpu_map.values())

    for idx, gpu in enumerate(results):
        gpu["index"] = idx
        gpu["memory_total_mb"] = _sanitize_gpu_memory_total(gpu.get("vendor"), gpu.get("memory_total_mb"))

    return results


def get_generic_gpus() -> List[Dict[str, Any]]:
    """
    Generic Windows fallback via WMI for AMD, Intel, and fallback NVIDIA visibility.
    """
    if platform.system().lower() != "windows":
        return []

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
        vendor = detect_gpu_vendor(name, video_processor)

        gpus.append(
            {
                "index": idx,
                "uuid": None,
                "name": name,
                "vendor": vendor,
                "load_percent": None,
                "memory_used_mb": None,
                "memory_total_mb": _sanitize_gpu_memory_total(vendor, _normalize_adapter_ram_mb(item.get("AdapterRAM"))),
                "temperature": None,
                "driver_version": item.get("DriverVersion"),
                "video_processor": video_processor,
                "pnp_device_id": item.get("PNPDeviceID"),
                "status": item.get("Status"),
                "source": "wmi",
            }
        )

    return gpus


def _normalize_name_for_match(name: Optional[str]) -> str:
    text = (name or "").lower()
    for token in (
        "nvidia",
        "amd",
        "intel",
        "geforce",
        "radeon",
        "graphics",
        "gpu",
        "series",
        "(tm)",
    ):
        text = text.replace(token, "")
    return " ".join(text.split())


def _prefer_gpu_memory_total(existing_gpu: Dict[str, Any], incoming_gpu: Dict[str, Any]) -> Optional[float]:
    existing = _sanitize_gpu_memory_total(existing_gpu.get("vendor"), existing_gpu.get("memory_total_mb"))
    incoming = _sanitize_gpu_memory_total(incoming_gpu.get("vendor"), incoming_gpu.get("memory_total_mb"))

    if incoming is None:
        return existing
    if existing is None:
        return incoming

    existing_source = (existing_gpu.get("source") or "").lower()
    incoming_source = (incoming_gpu.get("source") or "").lower()
    vendor = (existing_gpu.get("vendor") or incoming_gpu.get("vendor") or "").lower()

    if vendor == "amd":
        if "lhm" in incoming_source:
            return incoming
        if "lhm" in existing_source:
            return existing

    return max(existing, incoming)


def merge_gpu_lists(
    nvidia_gpus: List[Dict[str, Any]],
    generic_gpus: List[Dict[str, Any]],
    lhm_gpus: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    merged: List[Dict[str, Any]] = []
    used_generic = set()

    for ng in nvidia_gpus:
        merged_gpu = dict(ng)
        ng_name = _normalize_name_for_match(ng.get("name"))

        for idx, gg in enumerate(generic_gpus):
            if idx in used_generic:
                continue

            gg_name = _normalize_name_for_match(gg.get("name"))
            if gg.get("vendor") == "nvidia" and (
                ng_name == gg_name or ng_name in gg_name or gg_name in ng_name
            ):
                used_generic.add(idx)
                if merged_gpu.get("driver_version") is None:
                    merged_gpu["driver_version"] = gg.get("driver_version")
                if merged_gpu.get("pnp_device_id") is None:
                    merged_gpu["pnp_device_id"] = gg.get("pnp_device_id")
                if merged_gpu.get("status") in (None, "", "OK"):
                    merged_gpu["status"] = gg.get("status")
                if merged_gpu.get("memory_total_mb") is None:
                    merged_gpu["memory_total_mb"] = gg.get("memory_total_mb")
                break

        merged_gpu["memory_total_mb"] = _sanitize_gpu_memory_total(
            merged_gpu.get("vendor"),
            merged_gpu.get("memory_total_mb"),
        )
        merged.append(merged_gpu)

    for idx, gg in enumerate(generic_gpus):
        if idx in used_generic:
            continue
        if gg.get("vendor") == "nvidia" and nvidia_gpus:
            continue

        gg_copy = dict(gg)
        gg_copy["memory_total_mb"] = _sanitize_gpu_memory_total(
            gg_copy.get("vendor"),
            gg_copy.get("memory_total_mb"),
        )
        merged.append(gg_copy)

    for lg in lhm_gpus:
        lg_name = _normalize_name_for_match(lg.get("name"))
        matched = False

        for mg in merged:
            mg_name = _normalize_name_for_match(mg.get("name"))
            if lg_name and mg_name and (lg_name == mg_name or lg_name in mg_name or mg_name in lg_name):
                if lg.get("load_percent") is not None:
                    mg["load_percent"] = lg.get("load_percent")
                if lg.get("temperature") is not None:
                    mg["temperature"] = lg.get("temperature")
                if lg.get("memory_used_mb") is not None:
                    mg["memory_used_mb"] = lg.get("memory_used_mb")
                if lg.get("memory_total_mb") is not None:
                    mg["memory_total_mb"] = _prefer_gpu_memory_total(mg, lg)

                if mg.get("source") == "wmi":
                    mg["source"] = "lhm+wmi"
                elif mg.get("source") == "nvidia-smi":
                    mg["source"] = "nvidia-smi+lhm"
                elif mg.get("source") == "nvidia-smi-list":
                    mg["source"] = "nvidia-smi-list+lhm"

                mg["memory_total_mb"] = _sanitize_gpu_memory_total(
                    mg.get("vendor"),
                    mg.get("memory_total_mb"),
                )

                matched = True
                break

        if not matched:
            lg_copy = dict(lg)
            lg_copy["memory_total_mb"] = _sanitize_gpu_memory_total(
                lg_copy.get("vendor"),
                lg_copy.get("memory_total_mb"),
            )
            merged.append(lg_copy)

    for idx, gpu in enumerate(merged):
        gpu["index"] = idx
        gpu["memory_total_mb"] = _sanitize_gpu_memory_total(
            gpu.get("vendor"),
            gpu.get("memory_total_mb"),
        )

    return merged


def filter_gpu_list(gpus: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not gpus:
        return []

    filtered = [gpu for gpu in gpus if not is_virtual_gpu_name(gpu.get("name"))]

    if not filtered:
        filtered = list(gpus)

    has_discrete = any(
        not is_integrated_gpu_name(gpu.get("name")) and gpu.get("vendor") in {"nvidia", "amd"}
        for gpu in filtered
    )

    if has_discrete:
        filtered = [
            gpu for gpu in filtered
            if not is_integrated_gpu_name(gpu.get("name"))
        ] or filtered

    for idx, gpu in enumerate(filtered):
        gpu["index"] = idx
        gpu["memory_total_mb"] = _sanitize_gpu_memory_total(
            gpu.get("vendor"),
            gpu.get("memory_total_mb"),
        )

    return filtered


def choose_primary_gpu(gpus: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not gpus:
        return {}

    vendor_order = {"nvidia": 0, "amd": 1, "intel": 2, "unknown": 3}

    def primary_sort_key(gpu: Dict[str, Any]):
        name = gpu.get("name")
        is_virtual = 1 if is_virtual_gpu_name(name) else 0
        is_integrated = 1 if is_integrated_gpu_name(name) else 0
        vram = gpu.get("memory_total_mb") or 0

        return (
            is_virtual,
            is_integrated,
            vendor_order.get(gpu.get("vendor", "unknown"), 3),
            -vram,
        )

    primary = sorted(gpus, key=primary_sort_key)[0]

    return {
        "name": primary.get("name"),
        "vendor": primary.get("vendor"),
        "load_percent": primary.get("load_percent"),
        "memory_used_mb": primary.get("memory_used_mb"),
        "memory_total_mb": primary.get("memory_total_mb"),
        "temperature": primary.get("temperature"),
        "driver_version": primary.get("driver_version"),
        "source": primary.get("source"),
    }


def get_gpu_info() -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """
    Returns:
        primary_gpu, all_gpus
    """
    nvidia_gpus = get_nvidia_gpus()
    generic_gpus = get_generic_gpus()
    lhm_gpus = get_lhm_gpus()

    if not nvidia_gpus:
        nvidia_gpus = get_nvidia_gpu_list_fallback()

    merged = merge_gpu_lists(nvidia_gpus, generic_gpus, lhm_gpus)
    filtered = filter_gpu_list(merged)

    if not filtered:
        return {}, []

    return choose_primary_gpu(filtered), filtered


# -------------------------------------------------------------------
# Software inventory helpers
# -------------------------------------------------------------------

def _read_uninstall_key(root, path: str, source_name: str, entries: List[Dict[str, str]]) -> None:
    try:
        key = winreg.OpenKey(root, path)
    except OSError:
        return

    count = winreg.QueryInfoKey(key)[0]

    for i in range(count):
        try:
            subkey = winreg.OpenKey(key, winreg.EnumKey(key, i))
            name = winreg.QueryValueEx(subkey, "DisplayName")[0]
        except Exception:
            continue

        try:
            version = winreg.QueryValueEx(subkey, "DisplayVersion")[0]
        except Exception:
            version = ""

        try:
            publisher = winreg.QueryValueEx(subkey, "Publisher")[0]
        except Exception:
            publisher = ""

        try:
            install_date = winreg.QueryValueEx(subkey, "InstallDate")[0]
        except Exception:
            install_date = ""

        entries.append(
            {
                "source": source_name,
                "name": str(name),
                "version": str(version),
                "publisher": str(publisher),
                "install_date": str(install_date),
            }
        )


def get_software_inventory(limit: int = SOFTWARE_LIMIT) -> List[Dict[str, str]]:
    entries: List[Dict[str, str]] = []

    if platform.system().lower() == "windows":
        for root, path, source in [
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall", "registry_hklm"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall", "registry_wow6432"),
            (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall", "registry_hkcu"),
        ]:
            _read_uninstall_key(root, path, source, entries)

    seen = set()
    unique: List[Dict[str, str]] = []

    for item in entries:
        key = (item["name"], item["version"], item["publisher"])
        if key not in seen:
            seen.add(key)
            unique.append(item)

    unique.sort(key=lambda x: x["name"].lower())
    return unique[:limit]


# -------------------------------------------------------------------
# Agent event helpers
# -------------------------------------------------------------------

def get_agent_events() -> List[Dict[str, str]]:
    events = []

    for svc in get_watched_services():
        status = str(svc.get("status", "")).lower()
        if status not in ("running", ""):
            events.append(
                {
                    "event_type": "service_state",
                    "severity": "warning",
                    "message": f"Service {svc.get('display_name') or svc.get('service_name')} status is {status}",
                    "source": "agent",
                }
            )

    return events[:50]


# -------------------------------------------------------------------
# Data collection
# -------------------------------------------------------------------

def collect() -> Dict[str, Any]:
    vm = psutil.virtual_memory()
    disk = get_primary_disk_usage()
    primary_gpu, all_gpus = get_gpu_info()

    return {
        "api_key": API_KEY,
        "hostname": get_hostname(),
        "ip_address": get_ip(),
        "os_name": get_os_name(),
        "uptime_seconds": get_uptime_seconds(),
        "cpu_percent": psutil.cpu_percent(interval=1),
        "current_user": getpass.getuser(),
        "cpu_temp": get_cpu_temperature(),
        "ram": {
            "total": vm.total,
            "used": vm.used,
            "percent": vm.percent,
        },
        "disk": {
            "total": disk.total if disk else 0,
            "used": disk.used if disk else 0,
            "percent": disk.percent if disk else 0,
        },
        "network": get_network_totals(),
        "disk_io": get_disk_io(),
        "drives": get_all_drives(),
        "top_processes": get_top_processes(),
        "services": get_watched_services(),
        "interfaces": get_interfaces(),
        "inventory": get_inventory(),
        "software": get_software_inventory(),
        "gpu": primary_gpu,
        "gpus": all_gpus,
        "events": get_agent_events(),
    }


# -------------------------------------------------------------------
# Remote command execution
# -------------------------------------------------------------------

def execute_command(command: Dict[str, Any]) -> Tuple[bool, str]:
    action = command.get("action_type")
    payload = json.loads(command.get("payload_json") or "{}")

    if action == "restart_service":
        service_name = payload.get("service_name", "")
        if not service_name:
            return False, "Missing service_name"

        a = subprocess.run(["sc", "stop", service_name], capture_output=True, text=True, timeout=30)
        time.sleep(2)
        b = subprocess.run(["sc", "start", service_name], capture_output=True, text=True, timeout=30)

        return (
            b.returncode == 0,
            (a.stdout + "\n" + b.stdout + "\n" + a.stderr + "\n" + b.stderr).strip(),
        )

    if action == "stop_process":
        pid = payload.get("pid")
        if not pid:
            return False, "Missing pid"

        try:
            psutil.Process(int(pid)).terminate()
            return True, f"Process {pid} terminated"
        except Exception as exc:
            return False, str(exc)

    if action == "reboot_machine":
        delay = int(payload.get("delay_seconds", 5))
        r = subprocess.run(["shutdown", "/r", "/t", str(delay)], capture_output=True, text=True, timeout=10)
        return r.returncode == 0, (r.stdout + "\n" + r.stderr).strip()

    return False, f"Unsupported action: {action}"


def poll_commands() -> None:
    try:
        response = api_post(
            "/api/commands/next",
            {"api_key": API_KEY, "hostname": get_hostname()},
            timeout=15,
        )
        payload = response.json()
        command = payload.get("command")

        if not command:
            return

        ok, output = execute_command(command)

        api_post(
            "/api/commands/result",
            {
                "api_key": API_KEY,
                "command_id": command["id"],
                "status": "completed" if ok else "failed",
                "output": output[:4000],
            },
            timeout=20,
        )
    except Exception as exc:
        print(f"Command polling error: {exc}")


# -------------------------------------------------------------------
# Main loop
# -------------------------------------------------------------------

def main() -> None:
    global LHM_JSON_URL

    while True:
        try:
            runtime_settings = fetch_runtime_settings()

            if runtime_settings.get("enhanced_hwmon_enabled"):
                ensure_lhm_installed(runtime_settings)
                ensure_lhm_running(runtime_settings)
            else:
                LHM_JSON_URL = None

            payload = collect()
            response = api_post("/api/report", payload, timeout=30)

            primary_gpu = payload.get("gpu", {}).get("name", "n/a")
            gpu_names = [g.get("name", "unknown") for g in payload.get("gpus", [])]
            gpu_count = len(payload.get("gpus", []))

            print(
                f"Sent data: {response.status_code} | "
                f"{payload['hostname']} | "
                f"CPU {payload['cpu_percent']}% | "
                f"RAM {payload['ram']['percent']}% | "
                f"Primary GPU {primary_gpu} | "
                f"GPU Count {gpu_count} | "
                f"GPUs {gpu_names}"
            )

            if response.text:
                print(response.text)

        except Exception as exc:
            print(f"Error sending data: {exc}")

        poll_commands()
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()