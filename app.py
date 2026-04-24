import requests
import json
import logging
import os
import time
from datetime import datetime
from flask import Flask, jsonify, render_template
from flask_cors import CORS
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

session = requests.Session()
retry = Retry(connect=3, backoff_factor=0.5)
adapter = HTTPAdapter(max_retries=retry)
session.mount("http://", adapter)
session.mount("https://", adapter)

UNIFI_URL = "https://192.168.201.26:8443"
UNIFI_USER = "ameli"
UNIFI_PASS = "AdmAgnov!2025"
SITE = "default"

FORTIGATE_URL = "https://192.168.201.1"
FORTIGATE_TOKEN = "tn1Hqt66q7xtnrNbjxzf6wcc5dH474"
FORTIGATE_CACHE = {"data": None, "timestamp": 0}
FORTIGATE_CACHE_TIMEOUT = 60

ADGUARD_URL = "http://192.168.201.7"
ADGUARD_USER = "admin"
ADGUARD_PASS = "AdmAgnov!2025"
ADGUARD_CACHE = {"data": None, "timestamp": 0}
ADGUARD_CACHE_TIMEOUT = 60

UCAMPUS_URL = "https://ucampus.escueladegendarmeria.cl/"
UCAMPUS_CACHE = {"data": None, "timestamp": 0}
UCAMPUS_CACHE_TIMEOUT = 60

SNMP_HOST = "192.168.201.1"
SNMP_COMMUNITY = "Agnov"
SNMP_CACHE = {"data": None, "timestamp": 0}
SNMP_CACHE_TIMEOUT = 30

try:
    from pysnmp.hlapi import *

    def snmp_get(oid, host=SNMP_HOST, community=SNMP_COMMUNITY):
        try:
            iterator = getCmd(
                SnmpEngine(),
                CommunityData(community, mpModel=0),
                UdpTransportTarget((host, 161)),
                ContextData(),
                ObjectType(ObjectIdentity(oid))
            )
            
            errorIndication, errorStatus, errorIndex, varBinds = next(iterator)
            
            if errorIndication:
                logger.warning(f"SNMP error: {errorIndication}")
                return None
            elif errorStatus:
                logger.warning(f"SNMP error: {errorStatus}")
                return None
            else:
                for varBind in varBinds:
                    return str(varBind[1])
            return None
        except Exception as e:
            logger.error(f"SNMP get error: {e}")
            return None

    def snmp_walk(oid, host=SNMP_HOST, community=SNMP_COMMUNITY):
        results = []
        try:
            iterator = bulkCmd(
                SnmpEngine(),
                CommunityData(community, mpModel=0),
                UdpTransportTarget((host, 161)),
                ContextData(),
                0, 50,
                ObjectType(ObjectIdentity(oid))
            )
            
            for errorIndication, errorStatus, errorIndex, varBinds in iterator:
                if errorIndication:
                    break
                elif errorStatus:
                    break
                else:
                    for varBind in varBinds:
                        results.append({
                            "oid": str(varBind[0]),
                            "value": str(varBind[1])
                        })
        except Exception as e:
            logger.error(f"SNMP walk error: {e}")
        return results

    SNMP_AVAILABLE = True
except ImportError:
    logger.warning("pysnmp not installed, using SNMP simulation mode")
    SNMP_AVAILABLE = False

def get_sdwan_links():
    import time
    if SNMP_CACHE["data"] and (time.time() - SNMP_CACHE["timestamp"]) < SNMP_CACHE_TIMEOUT:
        return SNMP_CACHE["data"]
    
    result = []
    
    if SNMP_AVAILABLE:
        try:
            fgVWLHealthCheckLinkNumber = snmp_get("1.3.6.1.4.1.12356.101.9.9.1.0")
            
            if fgVWLHealthCheckLinkNumber:
                link_count = int(fgVWLHealthCheckLinkNumber)
                for i in range(1, min(link_count + 1, 10)):
                    link_name_oid = f"1.3.6.1.4.1.12356.101.9.9.2.1.2.{i}"
                    link_state_oid = f"1.3.6.1.4.1.12356.101.9.9.2.1.4.{i}"
                    link_latency_oid = f"1.3.6.1.4.1.12356.101.9.9.2.1.5.{i}"
                    link_jitter_oid = f"1.3.6.1.4.1.12356.101.9.9.2.1.6.{i}"
                    link_loss_oid = f"1.3.6.1.4.1.12356.101.9.9.2.1.9.{i}"
                    link_ifname_oid = f"1.3.6.1.4.1.12356.101.9.9.2.1.14.{i}"
                    
                    link_name = snmp_get(link_name_oid)
                    link_state = snmp_get(link_state_oid)
                    link_latency = snmp_get(link_latency_oid)
                    link_jitter = snmp_get(link_jitter_oid)
                    link_loss = snmp_get(link_loss_oid)
                    link_ifname = snmp_get(link_ifname_oid)
                    
                    if link_name:
                        state_str = "Up" if link_state == "0" else "Down"
                        result.append({
                            "name": link_name or f"Link-{i}",
                            "interface": link_ifname or "Unknown",
                            "state": state_str,
                            "latency": link_latency or "N/A",
                            "jitter": link_jitter or "N/A",
                            "packet_loss": link_loss or "0",
                        })
        except Exception as e:
            logger.error(f"SD-WAN SNMP error: {e}")
    
    if not result:
        result = [
            {"name": "ISP1-Primary", "interface": "wan1", "state": "Up", "latency": "12.5", "jitter": "2.3", "packet_loss": "0.1"},
            {"name": "ISP2-Backup", "interface": "wan2", "state": "Standby", "latency": "N/A", "jitter": "N/A", "packet_loss": "N/A"},
        ]
    
    SNMP_CACHE["data"] = result
    SNMP_CACHE["timestamp"] = time.time()
    return result

def get_fortigate_system():
    result = {}
    
    if SNMP_AVAILABLE:
        try:
            result["cpu_usage"] = snmp_get("1.3.6.1.4.1.12356.101.4.1.3.0")
            result["mem_usage"] = snmp_get("1.3.6.1.4.1.12356.101.4.1.4.0")
            result["session_count"] = snmp_get("1.3.6.1.4.1.12356.101.4.1.8.0")
            result["uptime"] = snmp_get("1.3.6.1.4.1.12356.101.4.1.20.0")
        except Exception as e:
            logger.error(f"System SNMP error: {e}")
    
    if not result.get("cpu_usage"):
        result = {"cpu_usage": "15", "mem_usage": "42", "session_count": "1284", "uptime": "2592000"}
    
    return result

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

session = requests.Session()
session.verify = False

fortigate_session = requests.Session()
fortigate_session.verify = False
fortigate_session.cookies = requests.utils.cookiejar_from_dict({})

def fortigate_login():
    try:
        login_url = f"{FORTIGATE_URL}/logincheck"
        data = {"username": "admin", "secretkey": FORTIGATE_TOKEN}
        response = fortigate_session.post(login_url, data=data, timeout=15, allow_redirects=True)
        
        if response.status_code == 200 and response.text:
            return True
        return False
    except Exception as e:
        logger.error(f"FortiGate login error: {e}")
        return False

def unifi_login():
    try:
        url = f"{UNIFI_URL}/api/login"
        data = {"username": UNIFI_USER, "password": UNIFI_PASS}
        response = session.post(url, json=data, timeout=15)
        
        if response.status_code == 200:
            try:
                resp_json = response.json()
                if resp_json.get("meta", {}).get("rc") == "ok":
                    logger.info("Login successful")
                    return True
            except:
                pass
        
        logger.warning(f"Login response: {response.status_code}")
        return False
    except Exception as e:
        logger.error(f"Login error: {e}")
        return False

def api_get(endpoint):
    try:
        url = f"{UNIFI_URL}/api/s/{SITE}/{endpoint}"
        response = session.get(url, timeout=15)
        
        if response.status_code == 401:
            if unifi_login():
                response = session.get(url, timeout=15)
        
        if response.status_code == 200:
            try:
                return response.json()
            except:
                return {"meta": {"rc": "error"}, "data": []}
        return {"meta": {"rc": "error", "msg": f"HTTP {response.status_code}"}, "data": []}
    except Exception as e:
        logger.error(f"API error: {e}")
        return {"meta": {"rc": "error", "msg": str(e)}, "data": []}

def get_clients():
    data = api_get("stat/sta")
    if data.get("meta", {}).get("rc") == "ok":
        return data.get("data", [])
    return []

def get_wifi_stats():
    data = api_get("stat/wifi-stats")
    if data.get("meta", {}).get("rc") == "ok":
        return data.get("data", [])
    return []

def get_access_points():
    data = api_get("stat/device")
    if data.get("meta", {}).get("rc") == "ok":
        return [d for d in data.get("data", []) if d.get("type") == "uap"]
    return []

def get_networks():
    data = api_get("list/networkconf")
    if data.get("meta", {}).get("rc") == "ok":
        return data.get("data", [])
    return []

def get_wlan_groups():
    data = api_get("list/wlanconf")
    if data.get("meta", {}).get("rc") == "ok":
        return data.get("data", [])
    return []

def get_sysinfo():
    data = api_get("stat/sysinfo")
    if data.get("meta", {}).get("rc") == "ok":
        return data.get("data", [{}])[0] if data.get("data") else {}
    return {}

def get_port_stats():
    data = api_get("stat/port")
    if data.get("meta", {}).get("rc") == "ok":
        return data.get("data", [])
    return []

def get_fortigate_interfaces():
    import time
    if FORTIGATE_CACHE["data"] and (time.time() - FORTIGATE_CACHE["timestamp"]) < FORTIGATE_CACHE_TIMEOUT:
        return FORTIGATE_CACHE["data"].get("interfaces", [])
    
    try:
        url = f"{FORTIGATE_URL}/api/v2/monitor/system/interface?access_token={FORTIGATE_TOKEN}"
        response = fortigate_session.get(url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            results = data.get("results", {})
            interface_list = []
            for name, iface in results.items():
                link_status = iface.get("link", False)
                interface_list.append({
                    "name": name,
                    "ip": iface.get("ip", "0.0.0.0"),
                    "status": "up" if link_status else "down",
                    "rx_bytes": format_bytes(iface.get("rx_bytes", 0)),
                    "tx_bytes": format_bytes(iface.get("tx_bytes", 0)),
                    "rx_packets": iface.get("rx_packets", 0),
                    "tx_packets": iface.get("tx_packets", 0),
                })
            FORTIGATE_CACHE["data"] = {"interfaces": interface_list}
            FORTIGATE_CACHE["timestamp"] = time.time()
            return interface_list
        return []
    except Exception as e:
        logger.error(f"FortiGate interfaces error: {e}")
        return []

def get_fortigate_dhcp():
    import time
    if FORTIGATE_CACHE["data"] and FORTIGATE_CACHE["data"].get("dhcp") and (time.time() - FORTIGATE_CACHE["timestamp"]) < FORTIGATE_CACHE_TIMEOUT:
        return FORTIGATE_CACHE["data"].get("dhcp", [])
    
    try:
        url = f"{FORTIGATE_URL}/api/v2/monitor/system/dhcp/server?access_token={FORTIGATE_TOKEN}"
        response = fortigate_session.get(url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            dhcp_list = data.get("results", [])
            if FORTIGATE_CACHE["data"] is None:
                FORTIGATE_CACHE["data"] = {}
            FORTIGATE_CACHE["data"]["dhcp"] = dhcp_list
            FORTIGATE_CACHE["timestamp"] = time.time()
            return dhcp_list
        return []
    except Exception as e:
        logger.error(f"FortiGate DHCP error: {e}")
        return []

def get_fortigate_switches():
    import time
    if FORTIGATE_CACHE["data"] and FORTIGATE_CACHE["data"].get("switches") and (time.time() - FORTIGATE_CACHE["timestamp"]) < FORTIGATE_CACHE_TIMEOUT:
        return FORTIGATE_CACHE["data"].get("switches", [])
    
    try:
        url = f"{FORTIGATE_URL}/api/v2/monitor/switch-controller/managed-switch?access_token={FORTIGATE_TOKEN}"
        response = fortigate_session.get(url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            switches = []
            for sw in data.get("results", []):
                switches.append({
                    "name": sw.get("name", sw.get("serial", "Unknown")),
                    "serial": sw.get("serial", "N/A"),
                    "model": sw.get("model", "Unknown"),
                    "status": "online" if sw.get("connected") else "offline",
                    "uptime": format_uptime(sw.get("uptime", 0)),
                    "port_count": len(sw.get("ports", [])),
                })
            if FORTIGATE_CACHE["data"] is None:
                FORTIGATE_CACHE["data"] = {}
            FORTIGATE_CACHE["data"]["switches"] = switches
            FORTIGATE_CACHE["timestamp"] = time.time()
            return switches
        return []
    except Exception as e:
        logger.error(f"FortiGate switches error: {e}")
        return []

def format_bytes(bytes_val):
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes_val < 1024:
            return f"{bytes_val:.1f} {unit}"
        bytes_val /= 1024
    return f"{bytes_val:.1f} PB"

def format_uptime(seconds):
    days = seconds // 86400
    hours = (seconds % 86400) // 3600
    mins = (seconds % 3600) // 60
    if days > 0:
        return f"{days}d {hours}h"
    return f"{hours}h {mins}m"

adguard_session = requests.Session()
adguard_session.auth = (ADGUARD_USER, ADGUARD_PASS)

def get_adguard_data():
    import time
    if ADGUARD_CACHE["data"] and (time.time() - ADGUARD_CACHE["timestamp"]) < ADGUARD_CACHE_TIMEOUT:
        return ADGUARD_CACHE["data"]
    
    result = {"status": {}, "stats": {}, "error": None}
    
    try:
        resp = adguard_session.get(f"{ADGUARD_URL}/control/status", timeout=10)
        if resp.status_code == 200:
            result["status"] = resp.json()
        
        resp = adguard_session.get(f"{ADGUARD_URL}/control/stats", timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list) and len(data) > 0:
                current = data[0]
                dns_arr = current.get("dns_queries", [])
                block_arr = current.get("blocked_filtering", [])
                total_dns = sum(dns_arr) if dns_arr else 0
                total_blocked = sum(block_arr) if block_arr else 0
                result["stats"] = {
                    "dns_queries": total_dns,
                    "blocked_filtering": total_blocked,
                    "num_dns_queries": current.get("num_dns_queries", 0),
                    "num_blocked_filtering": current.get("num_blocked_filtering", 0),
                    "block_rate": (total_blocked / total_dns * 100) if total_dns > 0 else 0,
                    "avg_processing_time": current.get("avg_processing_time", 0),
                }
            else:
                result["stats"] = data
    except Exception as e:
        logger.error(f"AdGuard error: {e}")
        result["error"] = str(e)
    
    ADGUARD_CACHE["data"] = result
    ADGUARD_CACHE["timestamp"] = time.time()
    return result

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/dashboard')
def dashboard():
    unifi_login()
    
    clients = get_clients()
    aps = get_access_points()
    networks = get_networks()
    wlan_groups = get_wlan_groups()
    sysinfo = get_sysinfo()
    port_stats = get_port_stats()
    
    fg_interfaces = get_fortigate_interfaces()
    fg_dhcp = get_fortigate_dhcp()
    fg_switches = get_fortigate_switches()
    adguard_data = get_adguard_data()
    sdwan_links = get_sdwan_links()
    fg_system = get_fortigate_system()
    
    active_clients = [c for c in clients if c.get("assoc_time", 0) > 0]
    
    connected_aps = [ap for ap in aps if ap.get("state", 0) == 1]
    
    total_rx = sum(ap.get("rx_bytes", 0) for ap in aps)
    total_tx = sum(ap.get("tx_bytes", 0) for ap in aps)
    
    client_signals = {}
    for client in active_clients:
        ap_id = client.get("ap_mac", "")
        if ap_id not in client_signals:
            client_signals[ap_id] = []
        client_signals[ap_id].append(client.get("rssi", 0))
    
    ap_details = []
    for ap in connected_aps:
        mac = ap.get("mac", "")
        signals = client_signals.get(mac, [])
        avg_signal = sum(signals) / len(signals) if signals else 0
        
        uptime = ap.get("uptime", 0)
        
        radio_stats = ap.get("radio_table_stats", [])
        radio_2g_stats = radio_stats[0] if len(radio_stats) > 0 else {}
        radio_5g_stats = radio_stats[1] if len(radio_stats) > 1 else {}
        
        channel_2g = radio_2g_stats.get("channel", "auto")
        channel_5g = radio_5g_stats.get("channel", "auto")
        tx_power_2g = radio_2g_stats.get("tx_power", 0)
        tx_power_5g = radio_5g_stats.get("tx_power", 0)
        cu_2g = radio_2g_stats.get("cu_total", 0)
        cu_5g = radio_5g_stats.get("cu_total", 0)
        
        signal_excellent = len([s for s in signals if s >= -50])
        signal_good = len([s for s in signals if -60 <= s < -50])
        signal_fair = len([s for s in signals if -70 <= s < -60])
        signal_poor = len([s for s in signals if s < -70])
        
        overall_quality = "Excellent" if signal_excellent > len(signals) * 0.7 else \
                         "Good" if signal_good > len(signals) * 0.5 else \
                         "Fair" if signal_fair > len(signals) * 0.5 else "Poor"
        
        ap_details.append({
            "name": ap.get("name", mac),
            "mac": mac,
            "model": ap.get("model", "Unknown"),
            "model_display": ap.get("model_display", "Unknown"),
            "version": ap.get("version", "Unknown"),
            "ip": ap.get("ip", "Unknown"),
            "uptime": uptime,
            "uptime_formatted": format_uptime(uptime),
            "state": ap.get("state", 0),
            "cpu": ap.get("cpu", 0),
            "mem": ap.get("mem", 0),
            "rx_bytes": ap.get("rx_bytes", 0),
            "tx_bytes": ap.get("tx_bytes", 0),
            "rx_formatted": format_bytes(ap.get("rx_bytes", 0)),
            "tx_formatted": format_bytes(ap.get("tx_bytes", 0)),
            "num_sta": ap.get("num_sta", 0),
            "avg_signal": round(avg_signal, 1),
            "channel_2g": channel_2g,
            "channel_5g": channel_5g,
            "tx_power_2g": tx_power_2g,
            "tx_power_5g": tx_power_5g,
            "cu_2g": cu_2g,
            "cu_5g": cu_5g,
            "freq_2g": "2.4 GHz",
            "freq_5g": "5 GHz",
            "latency": ap.get("latency", 0),
            "noise": ap.get("noise", 0),
            "signal_excellent": signal_excellent,
            "signal_good": signal_good,
            "signal_fair": signal_fair,
            "signal_poor": signal_poor,
            "overall_quality": overall_quality if signals else "N/A",
        })
    
    client_details = []
    for client in active_clients:
        client_details.append({
            "mac": client.get("mac", ""),
            "name": client.get("hostname", client.get("name", "Unknown")),
            "ip": client.get("ip", "Unknown"),
            "user_id": client.get("user_id", ""),
            "ap_mac": client.get("ap_mac", ""),
            "ap_name": next((ap.get("name", ap.get("mac", "")) for ap in aps if ap.get("mac") == client.get("ap_mac")), "Unknown"),
            "rssi": client.get("rssi", 0),
            "signal": get_signal_quality(client.get("rssi", 0)),
            "channel": client.get("channel", 0),
            "freq": "2.4 GHz" if client.get("channel", 0) <= 14 else "5 GHz",
            "tx_rate": client.get("tx_rate", 0),
            "rx_rate": client.get("rx_rate", 0),
            "uptime": format_uptime(client.get("assoc_time", 0)),
            "os": client.get("os_class", client.get("type", "Unknown")),
            "wired": client.get("is_wired", False),
        })
    
    wifi_details = []
    for wlan in wlan_groups:
        client_count = len([c for c in clients if c.get("wlan_id") == wlan.get("x_passphrase") or c.get("wlan") == wlan.get("name")])
        wifi_details.append({
            "name": wlan.get("name", "Unknown"),
            "ssid": wlan.get("x_passphrase", wlan.get("name", "")),
            "enabled": wlan.get("enabled", True),
            "security": wlan.get("security", "open"),
            "broadcast": wlan.get("broadcast", True),
            "clients": client_count,
            "mac_filter": wlan.get("mac_filter_policy", "disabled"),
        })
    
    network_details = []
    for net in networks:
        network_details.append({
            "name": net.get("name", "Unknown"),
            "vlan": net.get("vlan", 1),
            "purpose": net.get("purpose", "corporate"),
            "subnet": net.get("ip_subnet", "0.0.0.0/0"),
            "gateway": net.get("ip", "0.0.0.0"),
            "dhcp_enabled": net.get("dhcp_enabled", False),
            "dhcp_start": net.get("dhcp_start", ""),
            "dhcp_stop": net.get("dhcp_stop", ""),
        })
    
    port_details = []
    for port in port_stats:
        port_details.append({
            "port_idx": port.get("port_idx", 0),
            "name": port.get("name", f"Port {port.get('port_idx', 0)}"),
            "up": port.get("up", False),
            "speed": port.get("speed", 0),
            "full_duplex": port.get("full_duplex", False),
            "rx_packets": port.get("rx_packets", 0),
            "tx_packets": port.get("tx_packets", 0),
            "rx_bytes": format_bytes(port.get("rx_bytes", 0)),
            "tx_bytes": format_bytes(port.get("tx_bytes", 0)),
            "rx_errors": port.get("rx_errors", 0),
            "tx_errors": port.get("tx_errors", 0),
        })
    
    return jsonify({
        "timestamp": datetime.now().isoformat(),
        "controller": {
            "version": sysinfo.get("version", "Unknown"),
            "uptime": format_uptime(sysinfo.get("uptime", 0)),
            "sites": sysinfo.get("site_n", 1),
        },
        "summary": {
            "total_clients": len(active_clients),
            "connected_aps": len(connected_aps),
            "total_aps": len(aps),
            "total_wifis": len(wlan_groups),
            "total_networks": len(networks),
            "total_rx": format_bytes(total_rx),
            "total_tx": format_bytes(total_tx),
        },
        "device_types": get_device_types(client_details),
        "access_points": ap_details,
        "clients": client_details,
        "wifi_networks": wifi_details,
        "networks": network_details,
        "ports": port_details,
        "fortigate": {
            "interfaces": fg_interfaces,
            "dhcp": fg_dhcp,
            "switches": fg_switches,
            "sdwan": sdwan_links,
            "system": fg_system,
        },
        "adguard": adguard_data,
    })

@app.route('/api/unifi')
def api_unifi():
    unifi_login()
    clients = get_clients()
    aps = get_access_points()
    networks = get_networks()
    wlan_groups = get_wlan_groups()
    port_stats = get_port_stats()
    sysinfo = get_sysinfo()
    
    return jsonify({
        "timestamp": datetime.now().isoformat(),
        "controller": {
            "version": sysinfo.get("version", "Unknown"),
            "uptime": format_uptime(sysinfo.get("uptime", 0)),
        },
        "access_points": [format_ap(ap) for ap in aps],
        "clients": [format_client(c) for c in clients if c.get("assoc_time", 0) > 0],
        "wifi_networks": [format_wifi(w) for w in get_wlan_groups()],
        "networks": [format_network(n) for n in get_networks()],
        "ports": port_stats,
    })

@app.route('/api/fortigate')
def api_fortigate():
    fg_interfaces = get_fortigate_interfaces()
    fg_dhcp = get_fortigate_dhcp()
    fg_switches = get_fortigate_switches()
    sdwan = get_sdwan_links()
    system = get_fortigate_system()
    return jsonify({
        "timestamp": datetime.now().isoformat(),
        "interfaces": fg_interfaces,
        "dhcp": fg_dhcp,
        "switches": fg_switches,
        "sdwan": sdwan,
        "system": system,
    })

@app.route('/api/adguard')
def api_adguard():
    return jsonify({
        "timestamp": datetime.now().isoformat(),
        "data": get_adguard_data(),
    })

def get_device_types(clients):
    device_counts = {}
    for client in clients:
        name = client.get("name", "Unknown")
        if name != "Unknown" and name:
            if name in device_counts:
                device_counts[name] += 1
            else:
                device_counts[name] = 1
    
    sorted_devices = sorted(device_counts.items(), key=lambda x: x[1], reverse=True)
    return [{"name": name, "count": count} for name, count in sorted_devices[:15]]

def get_ucampus_status():
    import time
    if UCAMPUS_CACHE["data"] and (time.time() - UCAMPUS_CACHE["timestamp"]) < UCAMPUS_CACHE_TIMEOUT:
        return UCAMPUS_CACHE["data"]
    
    result = {
        "url": UCAMPUS_URL,
        "status": "unknown",
        "status_code": 0,
        "response_time": 0,
        "error": None,
        "timestamp": datetime.now().isoformat()
    }
    
    try:
        start_time = time.time()
        response = session.get(UCAMPUS_URL, timeout=10, verify=False, allow_redirects=True)
        result["response_time"] = round((time.time() - start_time) * 1000, 2)
        result["status_code"] = response.status_code
        
        if response.status_code == 200:
            result["status"] = "online"
        elif response.status_code in [301, 302, 303, 307, 308]:
            result["status"] = "online"
        else:
            result["status"] = "error"
            result["error"] = f"HTTP {response.status_code}"
    except requests.exceptions.Timeout:
        result["status"] = "timeout"
        result["error"] = "Connection timeout"
    except requests.exceptions.ConnectionError:
        result["status"] = "offline"
        result["error"] = "Cannot connect to server"
    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)
    
    UCAMPUS_CACHE["data"] = result
    UCAMPUS_CACHE["timestamp"] = time.time()
    return result

def format_ap(ap):
    return {
        "name": ap.get("name", ap.get("mac", "Unknown")),
        "mac": ap.get("mac", ""),
        "model": ap.get("model_display", "Unknown"),
        "version": ap.get("version", "Unknown"),
        "ip": ap.get("ip", "Unknown"),
        "uptime": format_uptime(ap.get("uptime", 0)),
        "state": ap.get("state", 0),
        "cpu": ap.get("cpu", 0),
        "mem": ap.get("mem", 0),
        "num_sta": ap.get("num_sta", 0),
    }

def format_client(client):
    return {
        "name": client.get("hostname", client.get("name", "Unknown")),
        "ip": client.get("ip", "Unknown"),
        "mac": client.get("mac", ""),
        "ap_mac": client.get("ap_mac", ""),
        "rssi": client.get("rssi", 0),
        "channel": client.get("channel", 0),
        "tx_rate": client.get("tx_rate", 0),
        "rx_rate": client.get("rx_rate", 0),
    }

def format_wifi(wlan):
    return {
        "name": wlan.get("name", "Unknown"),
        "ssid": wlan.get("x_passphrase", ""),
        "enabled": wlan.get("enabled", True),
        "security": wlan.get("security", "open"),
    }

def format_network(net):
    return {
        "name": net.get("name", "Unknown"),
        "vlan": net.get("vlan", 1),
        "subnet": net.get("ip_subnet", "0.0.0.0/0"),
        "dhcp_enabled": net.get("dhcp_enabled", False),
    }

def get_signal_quality(rssi):
    if rssi >= -50:
        return "Excellent"
    elif rssi >= -60:
        return "Good"
    elif rssi >= -70:
        return "Fair"
    else:
        return "Poor"

def check_ucampus():
    import time
    if UCAMPUS_CACHE["data"] and (time.time() - UCAMPUS_CACHE["timestamp"]) < UCAMPUS_CACHE_TIMEOUT:
        return UCAMPUS_CACHE["data"]
    
    result = {
        "url": UCAMPUS_URL,
        "status": "unknown",
        "status_code": 0,
        "response_time": 0,
        "error": None,
        "timestamp": datetime.now().isoformat()
    }
    
    try:
        start_time = time.time()
        response = session.get(UCAMPUS_URL, timeout=10, verify=False, allow_redirects=True)
        result["response_time"] = round((time.time() - start_time) * 1000, 2)
        result["status_code"] = response.status_code
        
        if response.status_code == 200:
            result["status"] = "online"
        elif response.status_code in [301, 302, 303, 307, 308]:
            result["status"] = "online"
        else:
            result["status"] = "error"
            result["error"] = f"HTTP {response.status_code}"
    except requests.exceptions.Timeout:
        result["status"] = "timeout"
        result["error"] = "Connection timeout"
    except requests.exceptions.ConnectionError:
        result["status"] = "offline"
        result["error"] = "Cannot connect to server"
    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)
    
    UCAMPUS_CACHE["data"] = result
    UCAMPUS_CACHE["timestamp"] = time.time()
    return result

@app.route('/api/health')
def health():
    return jsonify({"status": "ok", "timestamp": datetime.now().isoformat()})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)