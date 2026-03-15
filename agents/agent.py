import os
import sys

# Add project root before importing project modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import getpass
import json
import platform
import socket
import subprocess
import time
import winreg

import psutil
import requests
from services.service_name_utils import candidate_service_names, normalize_service_label

SERVER_URL = "http://127.0.0.1:5000"
API_KEY = "livewire-dev-key"
INTERVAL = 30
TOP_PROCESS_LIMIT = 8
SOFTWARE_LIMIT = 300
WATCH_SERVICES = ["Apache", "MySQL", "Spooler"]

_previous_net_totals = None
_previous_interface_totals = {}

def api_post(path, payload, timeout=30):
    return requests.post(f"{SERVER_URL}{path}", json=payload, timeout=timeout)

def get_ip():
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        sock.close()
        return ip
    except Exception:
        return "unknown"

def get_primary_disk_usage():
    try:
        if platform.system().lower() == "windows":
            return psutil.disk_usage("C:\\")
        return psutil.disk_usage("/")
    except Exception:
        return None

def get_all_drives():
    results = []
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
        results.append({
            "device": part.device, "mountpoint": part.mountpoint, "filesystem": part.fstype,
            "total_bytes": usage.total, "used_bytes": usage.used, "free_bytes": usage.free, "percent_used": usage.percent,
        })
    return results

def warm_process_cpu():
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            proc.cpu_percent(None)
        except Exception:
            pass
    time.sleep(0.15)

def get_top_processes(limit=TOP_PROCESS_LIMIT):
    warm_process_cpu()
    rows = []
    for proc in psutil.process_iter(["pid", "name", "memory_percent", "memory_info"]):
        try:
            info = proc.info
            rows.append({
                "pid": info.get("pid"),
                "name": info.get("name") or "unknown",
                "cpu_percent": proc.cpu_percent(None),
                "memory_percent": info.get("memory_percent") or 0,
                "memory_mb": round((info.get("memory_info").rss if info.get("memory_info") else 0) / (1024 ** 2), 2),
            })
        except Exception:
            pass
    return {
        "cpu": sorted(rows, key=lambda x: (x["cpu_percent"], x["memory_mb"]), reverse=True)[:limit],
        "memory": sorted(rows, key=lambda x: (x["memory_mb"], x["memory_percent"]), reverse=True)[:limit],
    }

def get_cpu_temperature():
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

def _get_windows_service_catalog():
    try:
        return [svc.as_dict() for svc in psutil.win_service_iter()]
    except Exception:
        return []


def _resolve_service_info(requested_name, catalog):
    candidates = [normalize_service_label(v) for v in candidate_service_names(requested_name)]
    if not candidates:
        return None

    for info in catalog:
        service_name = normalize_service_label(info.get("name"))
        display_name = normalize_service_label(info.get("display_name"))
        if service_name in candidates or display_name in candidates:
            return info
    return None


def get_watched_services():
    if platform.system().lower() != "windows":
        return []
    results = []
    catalog = _get_windows_service_catalog()
    for service_name in WATCH_SERVICES:
        info = _resolve_service_info(service_name, catalog)
        if info:
            results.append({
                "service_name": info.get("name"),
                "display_name": info.get("display_name") or info.get("name"),
                "status": info.get("status"),
                "start_type": info.get("start_type"),
                "username": info.get("username"),
                "binpath": info.get("binpath"),
                "requested_name": service_name,
            })
        else:
            results.append({"service_name": service_name, "display_name": service_name, "status": "not_found", "start_type": "", "username": "", "binpath": "", "requested_name": service_name})
    return results

def get_network_totals():
    global _previous_net_totals
    counters = psutil.net_io_counters()
    now = time.time()
    current = {"time": now, "sent": counters.bytes_sent, "recv": counters.bytes_recv}
    up_bps = down_bps = 0
    if _previous_net_totals:
        elapsed = max(now - _previous_net_totals["time"], 0.001)
        up_bps = max((current["sent"] - _previous_net_totals["sent"]) / elapsed, 0)
        down_bps = max((current["recv"] - _previous_net_totals["recv"]) / elapsed, 0)
    _previous_net_totals = current
    return {"bytes_sent": counters.bytes_sent, "bytes_recv": counters.bytes_recv, "up_bps": up_bps, "down_bps": down_bps}

def get_interfaces():
    global _previous_interface_totals
    results = []
    stats = psutil.net_if_stats()
    addrs = psutil.net_if_addrs()
    io = psutil.net_io_counters(pernic=True)
    now = time.time()
    for name, stat in stats.items():
        iface_addrs = addrs.get(name, [])
        ip_address = mac_address = None
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
        up_bps = down_bps = 0
        prev = _previous_interface_totals.get(name)
        if prev:
            elapsed = max(now - prev["time"], 0.001)
            up_bps = max((bytes_sent - prev["bytes_sent"]) / elapsed, 0)
            down_bps = max((bytes_recv - prev["bytes_recv"]) / elapsed, 0)
        _previous_interface_totals[name] = {"time": now, "bytes_sent": bytes_sent, "bytes_recv": bytes_recv}
        results.append({
            "interface_name": name, "is_up": bool(stat.isup), "speed_mbps": stat.speed, "mtu": stat.mtu,
            "ip_address": ip_address, "mac_address": mac_address,
            "bytes_sent": bytes_sent, "bytes_recv": bytes_recv, "up_bps": up_bps, "down_bps": down_bps,
        })
    return results

def get_inventory():
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

def get_gpu_info():
    try:
        result = subprocess.run(["nvidia-smi", "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu", "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=5)
        if result.returncode == 0 and result.stdout.strip():
            parts = [p.strip() for p in result.stdout.strip().splitlines()[0].split(",")]
            if len(parts) >= 5:
                return {"name": parts[0], "load_percent": float(parts[1]), "memory_used_mb": float(parts[2]), "memory_total_mb": float(parts[3]), "temperature": float(parts[4])}
    except Exception:
        pass
    return {}

def _read_uninstall_key(root, path, source_name, entries):
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
        try: version = winreg.QueryValueEx(subkey, "DisplayVersion")[0]
        except Exception: version = ""
        try: publisher = winreg.QueryValueEx(subkey, "Publisher")[0]
        except Exception: publisher = ""
        try: install_date = winreg.QueryValueEx(subkey, "InstallDate")[0]
        except Exception: install_date = ""
        entries.append({"source": source_name, "name": str(name), "version": str(version), "publisher": str(publisher), "install_date": str(install_date)})

def get_software_inventory(limit=SOFTWARE_LIMIT):
    entries = []
    if platform.system().lower() == "windows":
        for root, path, source in [
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall", "registry_hklm"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall", "registry_wow6432"),
            (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall", "registry_hkcu"),
        ]:
            _read_uninstall_key(root, path, source, entries)
    seen, unique = set(), []
    for item in entries:
        key = (item["name"], item["version"], item["publisher"])
        if key not in seen:
            seen.add(key)
            unique.append(item)
    unique.sort(key=lambda x: x["name"].lower())
    return unique[:limit]

def get_agent_events():
    events = []
    for svc in get_watched_services():
        status = str(svc.get("status", "")).lower()
        if status not in ("running", ""):
            events.append({"event_type": "service_state", "severity": "warning", "message": f"Service {svc.get('display_name') or svc.get('service_name')} status is {status}", "source": "agent"})
    return events[:50]

def collect():
    vm = psutil.virtual_memory()
    disk = get_primary_disk_usage()
    diskio = psutil.disk_io_counters()
    return {
        "api_key": API_KEY,
        "hostname": socket.gethostname(),
        "ip_address": get_ip(),
        "os_name": f"{platform.system()} {platform.release()}",
        "uptime_seconds": int(time.time() - psutil.boot_time()),
        "cpu_percent": psutil.cpu_percent(interval=1),
        "current_user": getpass.getuser(),
        "cpu_temp": get_cpu_temperature(),
        "ram": {"total": vm.total, "used": vm.used, "percent": vm.percent},
        "disk": {"total": disk.total if disk else 0, "used": disk.used if disk else 0, "percent": disk.percent if disk else 0},
        "network": get_network_totals(),
        "disk_io": {"read_bytes": diskio.read_bytes if diskio else 0, "write_bytes": diskio.write_bytes if diskio else 0},
        "drives": get_all_drives(),
        "top_processes": get_top_processes(),
        "services": get_watched_services(),
        "interfaces": get_interfaces(),
        "inventory": get_inventory(),
        "software": get_software_inventory(),
        "gpu": get_gpu_info(),
        "events": get_agent_events(),
    }

def execute_command(command):
    action = command.get("action_type")
    payload = json.loads(command.get("payload_json") or "{}")
    if action == "restart_service":
        service_name = payload.get("service_name", "")
        if not service_name:
            return False, "Missing service_name"
        a = subprocess.run(["sc", "stop", service_name], capture_output=True, text=True, timeout=30)
        time.sleep(2)
        b = subprocess.run(["sc", "start", service_name], capture_output=True, text=True, timeout=30)
        return b.returncode == 0, (a.stdout + "\n" + b.stdout + "\n" + a.stderr + "\n" + b.stderr).strip()
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

def poll_commands():
    try:
        response = api_post("/api/commands/next", {"api_key": API_KEY, "hostname": socket.gethostname()}, timeout=15)
        payload = response.json()
        command = payload.get("command")
        if not command:
            return
        ok, output = execute_command(command)
        api_post("/api/commands/result", {"api_key": API_KEY, "command_id": command["id"], "status": "completed" if ok else "failed", "output": output[:4000]}, timeout=20)
    except Exception as exc:
        print(f"Command polling error: {exc}")

def main():
    while True:
        try:
            payload = collect()
            response = api_post("/api/report", payload, timeout=30)
            print(f"Sent data: {response.status_code} | {payload['hostname']} | CPU {payload['cpu_percent']}% | RAM {payload['ram']['percent']}%")
            if response.text:
                print(response.text)
        except Exception as exc:
            print(f"Error sending data: {exc}")
        poll_commands()
        time.sleep(INTERVAL)

if __name__ == "__main__":
    main()
