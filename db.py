import mariadb
import config
from datetime import datetime


def get_connection():
    return mariadb.connect(
        host=config.DB_HOST,
        port=config.DB_PORT,
        user=config.DB_USER,
        password=config.DB_PASSWORD,
        database=config.DB_NAME,
        autocommit=True,
    )


def get_servers():
    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT * FROM servers ORDER BY name")
    rows = cur.fetchall()
    conn.close()
    return rows


def get_server(server_id):
    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT * FROM servers WHERE id = ?", (server_id,))
    row = cur.fetchone()
    conn.close()
    return row


def add_server(name, ip_address, agent_port, auth_token, os_type):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO servers (name, ip_address, agent_port, auth_token, os_type) VALUES (?, ?, ?, ?, ?)",
        (name, ip_address, agent_port, auth_token, os_type),
    )
    conn.close()


def delete_server(server_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM servers WHERE id = ?", (server_id,))
    conn.close()


def get_latest_metrics(server_id):
    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute(
        "SELECT * FROM metrics WHERE server_id = ? ORDER BY recorded_at DESC LIMIT 1",
        (server_id,),
    )
    row = cur.fetchone()
    conn.close()
    return row


def get_metric_history(server_id, limit=20):
    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute(
        "SELECT * FROM metrics WHERE server_id = ? ORDER BY recorded_at DESC LIMIT ?",
        (server_id, limit),
    )
    rows = cur.fetchall()
    conn.close()
    return list(reversed(rows))


def insert_metrics(server_id, cpu, memory, disk, uptime_seconds):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO metrics (server_id, cpu_percent, memory_percent, disk_percent, uptime_seconds) VALUES (?, ?, ?, ?, ?)",
        (server_id, cpu, memory, disk, uptime_seconds),
    )
    conn.close()


def update_server_status(server_id, status):
    conn = get_connection()
    cur = conn.cursor()
    if status == "online":
        cur.execute(
            "UPDATE servers SET status = ?, last_seen = NOW() WHERE id = ?",
            (status, server_id),
        )
    else:
        cur.execute(
            "UPDATE servers SET status = ? WHERE id = ?",
            (status, server_id),
        )
    conn.close()


def get_server_status(server_id):
    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT status FROM servers WHERE id = ?", (server_id,))
    row = cur.fetchone()
    conn.close()
    return row["status"] if row else None


def log_event(server_id, user_id, event_type, description, ip_address=None):
    """Record a system or user event.  ip_address is optional (stored when available)."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO event_logs (server_id, user_id, event_type, description, ip_address)"
        " VALUES (?, ?, ?, ?, ?)",
        (server_id, user_id, event_type, description, ip_address),
    )
    conn.close()


def log_command(server_id, user_id, command, output, ip_address=None):
    """Record a remote command execution.  ip_address is optional (stored when available)."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO command_logs (server_id, user_id, command, output, ip_address)"
        " VALUES (?, ?, ?, ?, ?)",
        (server_id, user_id, command, output, ip_address),
    )
    conn.close()


def get_logs(search=None, page=1, per_page=50):
    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    offset = (page - 1) * per_page

    if search:
        like = f"%{search}%"
        cur.execute(
            """
            SELECT 'command' AS log_type, cl.id, cl.executed_at AS ts,
                   s.name AS server_name, u.username,
                   cl.command AS detail, cl.output AS extra
            FROM command_logs cl
            LEFT JOIN servers s ON cl.server_id = s.id
            LEFT JOIN users u ON cl.user_id = u.id
            WHERE cl.command LIKE ? OR cl.output LIKE ? OR s.name LIKE ? OR u.username LIKE ?
            UNION ALL
            SELECT 'event' AS log_type, el.id, el.timestamp AS ts,
                   s.name AS server_name, NULL AS username,
                   el.event_type AS detail, el.description AS extra
            FROM event_logs el
            LEFT JOIN servers s ON el.server_id = s.id
            WHERE el.event_type LIKE ? OR el.description LIKE ? OR s.name LIKE ?
            ORDER BY ts DESC
            LIMIT ? OFFSET ?
            """,
            (like, like, like, like, like, like, like, per_page, offset),
        )
    else:
        cur.execute(
            """
            SELECT 'command' AS log_type, cl.id, cl.executed_at AS ts,
                   s.name AS server_name, u.username,
                   cl.command AS detail, cl.output AS extra
            FROM command_logs cl
            LEFT JOIN servers s ON cl.server_id = s.id
            LEFT JOIN users u ON cl.user_id = u.id
            UNION ALL
            SELECT 'event' AS log_type, el.id, el.timestamp AS ts,
                   s.name AS server_name, NULL AS username,
                   el.event_type AS detail, el.description AS extra
            FROM event_logs el
            LEFT JOIN servers s ON el.server_id = s.id
            ORDER BY ts DESC
            LIMIT ? OFFSET ?
            """,
            (per_page, offset),
        )
    rows = cur.fetchall()
    conn.close()
    return rows


def get_user_by_username(username):
    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT * FROM users WHERE username = ?", (username,))
    row = cur.fetchone()
    conn.close()
    return row


def create_user(username, password_hash):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO users (username, password_hash) VALUES (?, ?)",
        (username, password_hash),
    )
    conn.close()


def get_servers_with_latest_metrics():
    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute(
        """
        SELECT s.*,
               m.cpu_percent, m.memory_percent, m.disk_percent,
               m.uptime_seconds, m.recorded_at AS metrics_at
        FROM servers s
        LEFT JOIN metrics m ON m.id = (
            SELECT id FROM metrics
            WHERE server_id = s.id
            ORDER BY recorded_at DESC
            LIMIT 1
        )
        ORDER BY s.name
        """
    )
    rows = cur.fetchall()
    conn.close()
    return rows