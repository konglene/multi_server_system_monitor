# sysmon

A self-hosted server monitoring dashboard. Deploy a lightweight agent on every server you want to watch, point them at the central dashboard, and get live CPU, RAM, disk, and uptime metrics — plus a remote command runner and full audit log.

---

## How it works — agent to dashboard

```
[monitored server]                    [your machine]
  agent.py                              browser
     │                                     │
     │  Flask app exposes:                 │  HTTPS request
     │  GET  /metrics  → JSON             │       │
     │  POST /command  → run + return      ▼       ▼
     │                               ┌─────────────────┐
     │                               │      nginx      │  ← TLS termination
     │◄──────────────────────────────│  (port 443/80)  │
     │   monitor.py polls /metrics   └────────┬────────┘
     │   every 10 seconds                     │ proxy_pass
     │   via background thread                ▼
     │                               ┌─────────────────┐
     │   results stored in           │    Gunicorn      │
     └──────────────────────────────►│    app.py        │
         MariaDB: metrics table      │    monitor.py    │
                                     └────────┬────────┘
                                              │
                                     ┌────────▼────────┐
                                     │    MariaDB       │
                                     │  metrics         │
                                     │  servers         │
                                     │  command_logs    │
                                     │  event_logs      │
                                     │  users           │
                                     └─────────────────┘
```

**Step by step:**

1. `agent.py` starts on a monitored server. It generates a secret token (or reads one from `AGENT_TOKEN`) and listens on port `5001` with two endpoints: `/metrics` returns live CPU/RAM/disk/uptime as JSON, `/command` executes a shell command and returns the output if the token matches.

2. On the central server, `monitor.py` runs as a background daemon thread inside the Flask process. Every 10 seconds it loops through every server in the database, calls `GET /metrics` on each agent, and writes the result to the `metrics` table in MariaDB. If an agent stops responding, the server's status is flipped to `offline` and an event is logged.

3. When you open the dashboard in your browser, Flask renders `dashboard.html` server-side with the latest metrics from the database — so you see data immediately with no blank flash. After load, `dashboard.js` calls `GET /api/servers` every 10 seconds and updates each card in place.

4. nginx sits in front of everything, terminates HTTPS, redirects plain HTTP to HTTPS, and forwards requests to Gunicorn on `127.0.0.1:5000`. Flask itself never speaks TLS.

---

## Technologies

| Technology | Role | Why |
|---|---|---|
| **Flask** | Web framework | Lightweight, built-in Jinja2 templating, easy routing — right-sized for an internal tool |
| **Gunicorn** | WSGI server | Flask's dev server is single-threaded and not production-safe; Gunicorn handles concurrent requests properly |
| **nginx** | Reverse proxy | Handles TLS termination, HTTP→HTTPS redirect, security headers, and connection buffering in front of Gunicorn |
| **MariaDB** | Database | Stores metric history, user accounts, command logs, and event logs — relational model fits the structured data well |
| **psutil** | System metrics | Cross-platform Python library for reading CPU, RAM, disk, and uptime from the OS |
| **bcrypt** | Password hashing | Slow-by-design hashing algorithm — makes brute-forcing stolen password hashes impractical |
| **requests** | HTTP client | Used by `monitor.py` and `app.py` to call agent endpoints |
| **Werkzeug** | WSGI utilities | Flask is built on it; used here for `ProxyFix` to correctly read client IPs behind nginx |

---

## File structure

```
sysmon/
├── agent.py                 Lightweight Flask app — runs on every monitored server
├── app.py                   Central Flask app — routes, API, session handling
├── auth.py                  Login, @login_required decorator, bcrypt helpers
├── config.example.py        Configuration template — copy to config.py and fill in
├── config.py                Your live config (gitignored — never committed)
├── create_admin.py          One-time script to create the first admin user
├── db.py                    All MariaDB queries (servers, metrics, logs, users)
├── generate_certs.sh        Generates a CA + per-agent TLS certs for mTLS setup
├── init_db.py               Creates all database tables (safe to re-run)
├── monitor.py               Background thread — polls agents every 10 seconds
├── requirements.txt         Python dependencies
├── nginx.conf               nginx reverse proxy config
├── deploy/
│   ├── sysmon.service       systemd unit for the central Flask app
│   └── sysmon-agent.service systemd unit for the agent (deploy on each server)
├── static/
│   ├── style.css            All styling
│   └── dashboard.js         Live card updates, history modal
└── templates/
    ├── base.html            Layout, nav bar, flash messages
    ├── dashboard.html       Live server grid
    ├── servers.html         Add / remove servers
    ├── commands.html        Remote command runner
    └── logs.html            Event and command audit log
```

---

## Deployment

### 1. Prerequisites

arch
```bash
sudo pacman -S mariadb nginx python
```

debian
```bash
sudo apt update
sudo apt install mariadb nginx python
```

Start and initialise MariaDB:

```bash
sudo systemctl enable --now mariadb
sudo mariadb-install-db --user=mysql --basedir=/usr --datadir=/var/lib/mysql
sudo mysql_secure_installation
```

### 2. Database

```sql
sudo mariadb -u root -p

CREATE DATABASE sysmon;
CREATE USER 'sysmon'@'localhost' IDENTIFIED BY 'your_db_password';
GRANT ALL PRIVILEGES ON sysmon.* TO 'sysmon'@'localhost';
EXIT;
```

### 3. Clone and configure

```bash
git clone https://github.com/YOUR_USERNAME/sysmon.git /opt/sysmon
cd /opt/sysmon

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp config.example.py config.py
```

Edit `config.py` — set your DB password and generate a secret key:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

Paste the output as `SECRET_KEY` in `config.py`.

### 4. Initialise database and create admin user

```bash
python3 init_db.py
python3 create_admin.py admin your_chosen_password
```

### 5. nginx

Generate a self-signed cert (or use Let's Encrypt — see bottom of this file):

```bash
sudo openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
  -keyout /etc/ssl/private/sysmon.key \
  -out    /etc/ssl/certs/sysmon.crt   \
  -subj   "/CN=sysmon"
```

Deploy the config:

```bash
sudo mkdir -p /etc/nginx/conf.d
sudo cp nginx.conf /etc/nginx/conf.d/sysmon.conf
```

Add inside the `http {}` block of `/etc/nginx/nginx.conf` if not already there:

```nginx
include /etc/nginx/conf.d/*.conf;
```

```bash
sudo nginx -t && sudo systemctl enable --now nginx
```

### 6. systemd service

Edit `deploy/sysmon.service` — replace `YOUR_USER` with your Linux username and update paths if you did not use `/opt/sysmon`:

```bash
sudo cp deploy/sysmon.service /etc/systemd/system/sysmon.service
sudo systemctl daemon-reload
sudo systemctl enable --now sysmon
sudo systemctl status sysmon
```

Open `https://localhost` in your browser and log in with the credentials from step 4.

---

## Agent deployment

Do this on **every server you want to monitor**.

### Linux

```bash
scp agent.py user@server-ip:/opt/sysmon/agent.py
ssh user@server-ip

pip install flask psutil
python3 /opt/sysmon/agent.py
```

Note the `AUTH TOKEN` printed on startup — you need it when adding the server in the dashboard.

To run as a persistent service, edit `deploy/sysmon-agent.service` — replace `YOUR_AGENT_TOKEN` with the token printed above, then copy it to the agent server and enable it:

```bash
sudo cp sysmon-agent.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now sysmon-agent
```

### Windows

```cmd
pip install flask psutil
set AGENT_TOKEN=your_token_here
python C:\sysmon\agent.py
```

Use [NSSM](https://nssm.cc/) to register it as a Windows service for persistence.

### Add the server in the dashboard

Go to **Servers → Add Server**:

| Field | Value |
|---|---|
| Name | Anything descriptive, e.g. `prod-web-01` |
| IP Address | The server's IP |
| Agent Port | `5001` (default) |
| Auth Token | The token printed by `agent.py` on first run |
| OS Type | Linux / Windows |

The dashboard will start showing metrics within 10 seconds.

---

## Optional: mTLS between dashboard and agents

By default agents communicate over plain HTTP. To encrypt agent traffic with mutual TLS:

```bash
chmod +x generate_certs.sh
./generate_certs.sh agent1 agent2 agent3
```

This creates `certs/ca.crt`, `certs/ca.key`, and a cert+key pair per agent name. Then:

```bash
sudo mkdir -p /etc/sysmon
sudo cp certs/ca.crt /etc/sysmon/ca.crt
```

For each agent server:

```bash
scp certs/agent1.crt root@agent1-ip:/etc/sysmon/agent.crt
scp certs/agent1.key root@agent1-ip:/etc/sysmon/agent.key
```

On each agent, add to the systemd `[Service]` section:

```ini
Environment=AGENT_CERT=/etc/sysmon/agent.crt
Environment=AGENT_KEY=/etc/sysmon/agent.key
```

In `config.py` on the central server:

```python
AGENT_TLS     = True
AGENT_CA_CERT = "/etc/sysmon/ca.crt"
```

```bash
sudo systemctl restart sysmon
```

---

## Let's Encrypt (public domain)

If your server has a public domain name, replace the self-signed cert with a trusted one:

arch
```bash
sudo pacman -S certbot certbot-nginx
sudo certbot --nginx -d yourdomain.com
```
debian
```bash
sudo apt install certbot certbot-nginx
sudo certbot --nginx -d yourdomain.com
```


Certbot automatically updates `nginx.conf` and sets up auto-renewal.

---

## Useful commands

```bash
sudo systemctl restart sysmon                        # restart after code changes
journalctl -u sysmon -f                              # live app logs
journalctl -u sysmon-agent -f                        # live agent logs (on agent server)
sudo nginx -t && sudo systemctl reload nginx         # reload nginx after config changes
```
