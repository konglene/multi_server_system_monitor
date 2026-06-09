import bcrypt
from functools import wraps
from flask import session, redirect, url_for, flash
import db


def check_password(plain, hashed):
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


def hash_password(plain):
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in to continue.", "warning")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


def try_login(username, password):
    user = db.get_user_by_username(username)
    if user and check_password(password, user["password_hash"]):
        return user
    return None