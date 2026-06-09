import bcrypt
import mariadb
import config
import sys


def create_admin(username="admin", password="admin2110"):
    pw_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    conn = mariadb.connect(
        host=config.DB_HOST,
        port=config.DB_PORT,
        user=config.DB_USER,
        password=config.DB_PASSWORD,
        database=config.DB_NAME,
        autocommit=True,
    )
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO users (username, password_hash) VALUES (?, ?)",
            (username, pw_hash),
        )
        print(f"[create_admin] User '{username}' created successfully.")
        print(f"[create_admin] Login with username: {username}  password: {password}")
    except mariadb.IntegrityError:
        print(f"[create_admin] User '{username}' already exists. Skipping.")
    finally:
        conn.close()


if __name__ == "__main__":
    u = sys.argv[1] if len(sys.argv) > 1 else "admin"
    p = sys.argv[2] if len(sys.argv) > 2 else "admin2110"
    create_admin(u, p)