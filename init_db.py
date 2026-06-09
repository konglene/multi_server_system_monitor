import mariadb
import config

DDL = [
    """
    CREATE TABLE IF NOT EXISTS users (
        id INT AUTO_INCREMENT PRIMARY KEY,
        username VARCHAR(50) UNIQUE NOT NULL,
        password_hash VARCHAR(255) NOT NULL,
        created_at DATETIME DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS servers (
        id INT AUTO_INCREMENT PRIMARY KEY,
        name VARCHAR(50) NOT NULL,
        ip_address VARCHAR(45) NOT NULL,
        agent_port INT DEFAULT 5001,
        auth_token VARCHAR(100) NOT NULL,
        os_type VARCHAR(10) DEFAULT 'linux',
        status VARCHAR(10) DEFAULT 'offline',
        last_seen DATETIME
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS metrics (
        id INT AUTO_INCREMENT PRIMARY KEY,
        server_id INT,
        cpu_percent FLOAT,
        memory_percent FLOAT,
        disk_percent FLOAT,
        uptime_seconds BIGINT,
        recorded_at DATETIME DEFAULT NOW(),
        FOREIGN KEY (server_id) REFERENCES servers(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS command_logs (
        id INT AUTO_INCREMENT PRIMARY KEY,
        server_id INT,
        user_id INT,
        command TEXT,
        output LONGTEXT,
        ip_address VARCHAR(45),
        executed_at DATETIME DEFAULT NOW(),
        FOREIGN KEY (server_id) REFERENCES servers(id) ON DELETE SET NULL,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS event_logs (
        id INT AUTO_INCREMENT PRIMARY KEY,
        server_id INT NULL,
        user_id INT NULL,
        event_type VARCHAR(50),
        description TEXT,
        ip_address VARCHAR(45),
        timestamp DATETIME DEFAULT NOW()
    )
    """,
]

# Safe migrations for databases that already exist without the ip_address column.
# ADD COLUMN IF NOT EXISTS is supported in MariaDB 10.2+.
MIGRATIONS = [
    "ALTER TABLE command_logs ADD COLUMN IF NOT EXISTS ip_address VARCHAR(45) AFTER output",
    "ALTER TABLE event_logs   ADD COLUMN IF NOT EXISTS ip_address VARCHAR(45) AFTER description",
]


def init():
    conn = mariadb.connect(
        host=config.DB_HOST,
        port=config.DB_PORT,
        user=config.DB_USER,
        password=config.DB_PASSWORD,
        database=config.DB_NAME,
        autocommit=True,
    )
    cur = conn.cursor()
    for stmt in DDL:
        cur.execute(stmt)
    for stmt in MIGRATIONS:
        try:
            cur.execute(stmt)
        except mariadb.Error as e:
            # Non-fatal: column may already exist on older MariaDB versions
            # that don't support IF NOT EXISTS for ALTER TABLE.
            print(f"[init_db] Migration skipped (already applied?): {e}")
    conn.close()
    print("[init_db] All tables created / migrated (or already up to date).")


if __name__ == "__main__":
    init()