"""
sysmon agent — runs on every monitored server (Linux or Windows).

LINUX DEPLOYMENT
  1. Copy this file to the server
  2. pip install flask psutil
  3. python agent.py          ← token is auto-generated and printed
     (or set AGENT_TOKEN=your_token to pin a specific token)
     (or create a systemd service — see bottom of this file)

WINDOWS DEPLOYMENT
  1. Install Python 3 from python.org (check "Add to PATH")
  2. Copy this file to C:\sysmon\agent.py
  3. Open CMD as Administrator: pip install flask psutil
  4. python C:\sysmon\agent.py   ← token is auto-generated and printed
     (or set AGENT_TOKEN=your_token to pin a specific token)
     (or use NSSM to register as a Windows service)

TLS (HTTPS) — RECOMMENDED
  Generate a cert/key pair with generate_certs.sh, then set:
    export AGENT_CERT=/etc/sysmon/agent.crt
    export AGENT_KEY=/etc/sysmon/agent.key
  The agent will then listen on HTTPS instead of HTTP.
  Also update AGENT_TLS = True in config.py on the Flask server.

TOKEN PERSISTENCE
  If no AGENT_TOKEN env var is set, a random token is generated on first
  run and saved to agent_token.txt next to this file. Subsequent runs
  reuse the same token so you don't need to re-register the server.
  Delete agent_token.txt to rotate to a new token.

PORT
  Defaults to 5001. Override with AGENT_PORT env var, e.g.:
    export AGENT_PORT=5002   (if 5001 conflicts with another process)
"""

import os
import platform
import secrets
import subprocess
import time

import psutil
from flask import Flask, jsonify, request

app = Flask(__name__)

OS_TYPE   = platform.system()           # "Linux" or "Windows"
DISK_PATH = "C:\\" if OS_TYPE == "Windows" else "/"

# ─── Token resolution ─────────────────────────────────────────────────────────

_TOKEN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agent_token.txt")

def _resolve_token():
    if "AGENT_TOKEN" in os.environ:
        return os.environ["AGENT_TOKEN"], "env AGENT_TOKEN"

    if os.path.exists(_TOKEN_FILE):
        with open(_TOKEN_FILE) as f:
            token = f.read().strip()
        if token:
            return token, f"saved ({_TOKEN_FILE})"

    token = secrets.token_hex(24)
    with open(_TOKEN_FILE, "w") as f:
        f.write(token + "\n")
    return token, f"generated + saved to {_TOKEN_FILE}"

AGENT_TOKEN, _TOKEN_SOURCE = _resolve_token()

# ─── Port + TLS resolution ────────────────────────────────────────────────────
AGENT_PORT = int(os.environ.get("AGENT_PORT", 5001))

# Set AGENT_CERT and AGENT_KEY to the paths of your cert and key files.
# Leave unset (or empty) to run without TLS (plain HTTP).
AGENT_CERT = os.environ.get("AGENT_CERT", "").strip() or None
AGENT_KEY  = os.environ.get("AGENT_KEY",  "").strip() or None


# ─── Routes ───────────────────────────────────────────────────────────────────

@app.route("/metrics")
def metrics():
    cpu      = psutil.cpu_percent(interval=1)
    mem      = psutil.virtual_memory().percent
    disk     = psutil.disk_usage(DISK_PATH).percent
    uptime   = int(time.time() - psutil.boot_time())
    hostname = platform.node()

    return jsonify({
        "cpu":            cpu,
        "memory":         mem,
        "disk":           disk,
        "uptime_seconds": uptime,
        "os_type":        OS_TYPE.lower(),
        "hostname":       hostname,
    })


@app.route("/command", methods=["POST"])
def command():
    data  = request.get_json(force=True, silent=True) or {}
    token = data.get("token", "")
    cmd   = data.get("command", "").strip()

    if token != AGENT_TOKEN:
        return jsonify({"output": "", "error": "Unauthorized"}), 403

    if not cmd:
        return jsonify({"output": "", "error": "No command provided"}), 400

    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return jsonify({
            "output": result.stdout,
            "error":  result.stderr,
        })
    except subprocess.TimeoutExpired:
        return jsonify({"output": "", "error": "Command timed out after 30s"})
    except Exception as e:
        return jsonify({"output": "", "error": str(e)})


# ─── Start ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Build SSL context from cert + key paths if both are provided.
    # Flask passes this directly to Python's ssl module.
    ssl_ctx = (AGENT_CERT, AGENT_KEY) if AGENT_CERT and AGENT_KEY else None

    print("=" * 56)
    print("  sysmon agent")
    print("=" * 56)
    print(f"  OS          : {OS_TYPE}")
    print(f"  Disk path   : {DISK_PATH}")
    print(f"  Token source: {_TOKEN_SOURCE}")
    print()
    print(f"  AUTH TOKEN  : {AGENT_TOKEN}")
    print()
    if ssl_ctx:
        print(f"  TLS         : ENABLED")
        print(f"  Cert        : {AGENT_CERT}")
        print(f"  Key         : {AGENT_KEY}")
    else:
        print(f"  TLS         : disabled")
        print(f"  (set AGENT_CERT + AGENT_KEY env vars to enable)")
    print()
    print(f"  Copy the token above into the sysmon dashboard")
    print(f"  when adding this server.")
    print()
    print(f"  Listening   : 0.0.0.0:{AGENT_PORT}")
    print("=" * 56)

    app.run(
        host="0.0.0.0",
        port=AGENT_PORT,
        debug=False,
        use_reloader=False,
        ssl_context=ssl_ctx,    # None = plain HTTP, tuple = HTTPS
    )


# ─── systemd service (Linux) ──────────────────────────────────────────────────
#
#  Save as /etc/systemd/system/sysmon-agent.service then:
#    sudo systemctl daemon-reload
#    sudo systemctl enable --now sysmon-agent
#
# [Unit]
# Description=sysmon agent
# After=network.target
#
# [Service]
# ExecStart=/usr/bin/python3 /opt/sysmon/agent.py
# Environment=AGENT_TOKEN=your_secret_token
# Environment=AGENT_CERT=/etc/sysmon/agent.crt
# Environment=AGENT_KEY=/etc/sysmon/agent.key
# Restart=always
# RestartSec=5
#
# [Install]
# WantedBy=multi-user.target