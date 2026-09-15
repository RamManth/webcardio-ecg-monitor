"""
Local Subnet & Wi-Fi Hotspot Sensor Discovery Tool
==================================================
Scans the local network, Wi-Fi hotspot, and ARP table to locate the
WebCardio WC1340 / LifeSignals biosensor IP address and open streaming ports.
"""

import asyncio
import os
import re
import socket
import subprocess
from typing import Any, Dict, List, Optional


def get_local_ip_addresses() -> List[Dict[str, str]]:
    """Returns a list of active local IPv4 addresses and network interfaces."""
    interfaces = []
    try:
        # Connect to a public DNS IP temporarily to determine default outbound route
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.5)
        s.connect(("8.8.8.8", 80))
        primary_ip = s.getsockname()[0]
        s.close()
        interfaces.append({"name": "primary", "ip": primary_ip, "is_primary": True})
    except Exception:
        pass

    # Read all interfaces using ifconfig / socket
    try:
        hostname = socket.gethostname()
        for ip in socket.gethostbyname_ex(hostname)[2]:
            if not ip.startswith("127.") and not any(i["ip"] == ip for i in interfaces):
                interfaces.append({"name": "local", "ip": ip, "is_primary": False})
    except Exception:
        pass

    return interfaces


def get_arp_table() -> List[Dict[str, str]]:
    """Reads the current system ARP cache to list all active devices on the subnet."""
    devices = []
    try:
        proc = subprocess.run(["arp", "-a"], capture_output=True, text=True, timeout=3.0)
        output = proc.stdout
        # Example macOS output line:
        # ? (192.168.1.105) at 0:11:22:33:44:55 on en0 ifscope [ethernet]
        regex = r"\(([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+)\)\s+at\s+([0-9a-fA-F:]+)\s+on\s+(\w+)"
        for match in re.finditer(regex, output):
            ip = match.group(1)
            mac = match.group(2).lower()
            iface = match.group(3)
            if mac != "(incomplete)" and mac != "ff:ff:ff:ff:ff:ff":
                devices.append({
                    "ip": ip,
                    "mac": mac,
                    "interface": iface,
                    "vendor": _identify_vendor(mac)
                })
    except Exception:
        pass
    return devices


def _identify_vendor(mac: str) -> str:
    """Heuristic vendor identification for IoT and biosensor modules."""
    mac_clean = mac.replace(":", "").upper()
    prefix = mac_clean[:6]
    # Known prefixes for medical IoT, Espressif, Microchip, TI, Realtek, etc.
    vendor_hints = {
        "EC1BBD": "LifeSignals",
        "70B3D5": "IEEE IoT",
        "246F28": "Espressif",
        "A4CF12": "Espressif",
        "001EC0": "Microchip",
        "001A7D": "Murata",
    }
    return vendor_hints.get(prefix, "Generic Network Device")


async def scan_port(ip: str, port: int, timeout: float = 0.4) -> bool:
    """Asynchronously checks if a TCP port is open on target IP."""
    try:
        conn = asyncio.open_connection(ip, port)
        _, writer = await asyncio.wait_for(conn, timeout=timeout)
        writer.close()
        await writer.wait_closed()
        return True
    except Exception:
        return False


async def discover_sensor(candidate_ports: Optional[List[int]] = None) -> List[Dict[str, Any]]:
    """
    Performs network discovery for the WebCardio sensor:
    1. Scans ARP table
    2. Probes common medical IoT streaming ports (5000, 8080, 8000, 9000, 2000, 4000)
    """
    if candidate_ports is None:
        candidate_ports = [5000, 8080, 9000, 8000, 2000, 4000, 8888]

    arp_devices = get_arp_table()
    results = []

    for dev in arp_devices:
        ip = dev["ip"]
        open_ports = []
        for port in candidate_ports:
            is_open = await scan_port(ip, port)
            if is_open:
                open_ports.append(port)

        results.append({
            "ip": ip,
            "mac": dev["mac"],
            "interface": dev["interface"],
            "vendor": dev["vendor"],
            "open_ports": open_ports,
            "is_sensor_candidate": len(open_ports) > 0 or "LifeSignals" in dev["vendor"],
        })

    return results
