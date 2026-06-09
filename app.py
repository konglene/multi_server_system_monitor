import urllib3
import requests
from flask import (
    Flask, render_template, redirect, url_for,
    request, session, flash, jsonify,
)
import config, db, auth
from auth import login_required
from monitor import start_monitor

app = Flask(__name__)
app.secret_key = config.SECRET_KEY

# Suppress InsecureRequestWarning when verify=False (same reason as monitor.py)
if not config.AGENT_CA_CERT:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ─── Start monitor at module level ─────────────────────────────────────────────
start_monitor()


# ─── Template filters ──────────────────────────────────────────────────────────

@app.template_filter('uptime')
def uptime_filter(seconds):
    if not seconds:
        return '—'
    seconds = int(seconds)
    d = seconds // 86400
    h = (seconds % 86400) // 3600
    m = (seconds % 3600) // 60
    if d > 0:  return f'{d}d {h}h'
    if h > 0:  return f'{h}h {m}m'
    return f'{m}m'


# ─── Cache-busting for static files ───────────────────────────────────────────
import os as _os

@app.context_processor
def _inject_asset_url():
    def asset_url(filename):
        filepath = _os.path.join(app.static_folder, filename)
        try:
            mtime = int(_os.path.getmtime(filepath))
        except OSError:
            mtime = 0
        from flask import url_for as _uf
        return f"{_uf('static', filename=filename)}?v={mtime}"
    return dict(asset_url=asset_url)


# ─── Helpers ───────────────────────────────────────────────────────────────────

def client_ip():
    fwd = request.headers.get("X-Forwarded-For")
    return fwd.split(",")[0].strip() if fwd else request.remote_addr


def _agent_url(server, path):
    """Build the correct http:// or https:// agent URL based on config."""
    scheme = "https" if config.AGENT_TLS else "http"
    return f"{scheme}://{server['ip_address']}:{server['agent_port']}{path}"


# ─── Auth ──────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return redirect(url_for("dashboard") if "user_id" in session else url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        ip       = client_ip()
        user     = auth.try_login(username, password)
        if user:
            session["user_id"]  = user["id"]
            session["username"] = user["username"]
            db.log_event(None, user["id"], "login",
                         f"User '{username}' logged in.", ip_address=ip)
            return redirect(url_for("dashboard"))
        db.log_event(None, None, "login_fail",
                     f"Failed login for '{username}'.", ip_address=ip)
        flash("Invalid username or password.", "error")
    return render_template("login.html")


@app.route("/logout")
def logout():
    user_id  = session.get("user_id")
    username = session.get("username")
    ip       = client_ip()
    session.clear()
    if user_id:
        db.log_event(None, user_id, "logout",
                     f"User '{username}' logged out.", ip_address=ip)
    return redirect(url_for("login"))


# ─── Pages ─────────────────────────────────────────────────────────────────────

@app.route("/dashboard")
@login_required
def dashboard():
    return render_template("dashboard.html",
                           servers=db.get_servers_with_latest_metrics())


@app.route("/commands")
@login_required
def commands():
    return render_template("commands.html", servers=db.get_servers())


@app.route("/send_command", methods=["POST"])
@login_required
def send_command():
    server_id = request.form.get("server_id")
    command   = request.form.get("command", "").strip()
    user_id   = session["user_id"]
    ip        = client_ip()

    if not command:
        return jsonify({"error": "No command specified."}), 400

    targets = db.get_servers() if server_id == "all" else (
        [s] if (s := db.get_server(int(server_id))) else []
    )
    results = []
    for server in targets:
        url = _agent_url(server, "/command")
        try:
            resp   = requests.post(
                url,
                json={"command": command, "token": server["auth_token"]},
                timeout=30,
                verify=config.AGENT_CA_CERT,   # CA cert path, or False to skip
            )
            data   = resp.json()
            output = data.get("output", "") + data.get("error", "")
        except Exception as e:
            output = f"Connection error: {e}"
        db.log_command(server["id"], user_id, command, output, ip_address=ip)
        results.append({"server": server["name"], "output": output})

    return jsonify({"results": results})


@app.route("/logs")
@login_required
def logs():
    q    = request.args.get("q", "").strip()
    page = int(request.args.get("page", 1))
    return render_template("logs.html",
                           logs=db.get_logs(search=q or None, page=page),
                           q=q, page=page)


@app.route("/servers")
@login_required
def servers():
    return render_template("servers.html", servers=db.get_servers())


@app.route("/servers/add", methods=["POST"])
@login_required
def add_server():
    name    = request.form.get("name", "").strip()
    ip      = request.form.get("ip_address", "").strip()
    port    = int(request.form.get("agent_port", 5001))
    token   = request.form.get("auth_token", "").strip()
    os_type = request.form.get("os_type", "linux")
    c_ip    = client_ip()

    if not name or not ip or not token:
        flash("Name, IP, and token are required.", "error")
        return redirect(url_for("servers"))

    db.add_server(name, ip, port, token, os_type)
    db.log_event(None, session["user_id"], "server_add",
                 f"Added server '{name}' ({ip}:{port}).", ip_address=c_ip)
    flash(f"Server '{name}' added.", "success")
    return redirect(url_for("servers"))


@app.route("/servers/delete/<int:server_id>", methods=["POST"])
@login_required
def delete_server(server_id):
    s    = db.get_server(server_id)
    c_ip = client_ip()
    if s:
        db.delete_server(server_id)
        db.log_event(None, session["user_id"], "server_del",
                     f"Deleted server '{s['name']}'.", ip_address=c_ip)
        flash(f"Server '{s['name']}' deleted.", "success")
    return redirect(url_for("servers"))


# ─── JSON API ──────────────────────────────────────────────────────────────────

@app.route("/api/servers")
@login_required
def api_servers():
    result = []
    for s in db.get_servers_with_latest_metrics():
        result.append({
            "id":         s["id"],
            "name":       s["name"],
            "ip_address": s["ip_address"],
            "os_type":    s["os_type"],
            "status":     s["status"],
            "last_seen":  s["last_seen"].isoformat() if s["last_seen"] else None,
            "metrics": {
                "cpu_percent":    s["cpu_percent"],
                "memory_percent": s["memory_percent"],
                "disk_percent":   s["disk_percent"],
                "uptime_seconds": s["uptime_seconds"],
            },
        })
    return jsonify(result)


@app.route("/api/history/<int:server_id>")
@login_required
def api_history(server_id):
    result = []
    for r in db.get_metric_history(server_id, limit=20):
        result.append({
            "cpu_percent":    r["cpu_percent"],
            "memory_percent": r["memory_percent"],
            "disk_percent":   r["disk_percent"],
            "uptime_seconds": r["uptime_seconds"],
            "recorded_at":    r["recorded_at"].isoformat() if r["recorded_at"] else None,
        })
    return jsonify(result)


# ─── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)