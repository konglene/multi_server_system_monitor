import threading
import time
import requests
import urllib3
import db
import config

# Guard against being started twice (Flask werkzeug reloader imports modules twice)
_started = threading.Event()


def _agent_url(server, path):
    """Build the correct http:// or https:// URL based on config."""
    scheme = "https" if config.AGENT_TLS else "http"
    return f"{scheme}://{server['ip_address']}:{server['agent_port']}{path}"


def poll_servers():
    # Suppress InsecureRequestWarning when verify=False so logs stay clean.
    # This warning fires on every request, which would spam stdout every 10 s.
    if not config.AGENT_CA_CERT:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    while True:
        try:
            servers = db.get_servers()
            for server in servers:
                server_id   = server["id"]
                prev_status = server["status"]
                url         = _agent_url(server, "/metrics")
                try:
                    resp = requests.get(url, timeout=5, verify=config.AGENT_CA_CERT)
                    resp.raise_for_status()
                    data = resp.json()

                    db.insert_metrics(
                        server_id=server_id,
                        cpu=data.get("cpu", 0),
                        memory=data.get("memory", 0),
                        disk=data.get("disk", 0),
                        uptime_seconds=data.get("uptime_seconds", 0),
                    )
                    db.update_server_status(server_id, "online")

                    if prev_status != "online":
                        db.log_event(server_id, None, "online",
                                     f"Server '{server['name']}' came back online.")
                except Exception:
                    db.update_server_status(server_id, "offline")
                    if prev_status != "offline":
                        db.log_event(server_id, None, "offline",
                                     f"Server '{server['name']}' went offline.")

        except Exception as e:
            print(f"[monitor] Poll loop error: {e}")

        time.sleep(10)


def start_monitor():
    if _started.is_set():
        print("[monitor] Already running — skipping duplicate start.")
        return
    _started.set()
    t = threading.Thread(target=poll_servers, daemon=True, name="sysmon-monitor")
    t.start()
    print("[monitor] Background polling thread started.")