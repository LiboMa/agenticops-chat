"""Simple 3-tier Flask login app — ALB → EC2 → RDS (MySQL)."""

import os
import hashlib
import secrets
from datetime import datetime

from flask import Flask, render_template, request, redirect, url_for, session, flash
import pymysql

app, timezone= Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", secrets.token_hex(32))

# Database config from environment
DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_PORT = int(os.environ.get("DB_PORT", "3306"))
DB_NAME = os.environ.get("DB_NAME", "weblab")
DB_USER = os.environ.get("DB_USER", "weblab")
DB_PASS = os.environ.get("DB_PASS", "changeme")


def get_db():
    return pymysql.connect(
        host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASS,
        database=DB_NAME, cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=5, read_timeout=10,
    )


def hash_password(password: str, salt: str) -> str:
    return hashlib.sha256((salt + password).encode()).hexdigest()


def init_db():
    """Create users table and seed admin user if not exists."""
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    username VARCHAR(64) NOT NULL UNIQUE,
                    password_hash VARCHAR(128) NOT NULL,
                    salt VARCHAR(32) NOT NULL,
                    email VARCHAR(128),
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    last_login DATETIME,
                    login_count INT DEFAULT 0
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)
            # Seed admin user
            cur.execute("SELECT id FROM users WHERE username='admin'")
            if not cur.fetchone():
                salt = secrets.token_hex(16)
                pw_hash = hash_password("admin123", salt)
                cur.execute(
                    "INSERT INTO users (username, password_hash, salt, email) VALUES (%s, %s, %s, %s)",
                    ("admin", pw_hash, salt, "admin@tinyboat.blog"),
                )
            # Seed demo user
            cur.execute("SELECT id FROM users WHERE username='demo'")
            if not cur.fetchone():
                salt = secrets.token_hex(16)
                pw_hash = hash_password("demo123", salt)
                cur.execute(
                    "INSERT INTO users (username, password_hash, salt, email) VALUES (%s, %s, %s, %s)",
                    ("demo", pw_hash, salt, "demo@tinyboat.blog"),
                )
        conn.commit()
    finally:
        conn.close()


@app.route("/")
def index():
    if "user" in session:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        if not username or not password:
            flash("Please enter both username and password.", "error")
            return render_template("login.html")

        try:
            conn = get_db()
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM users WHERE username=%s", (username,))
                user = cur.fetchone()
                if user and hash_password(password, user["salt"]) == user["password_hash"]:
                    # Update login stats
                    cur.execute(
                        "UPDATE users SET last_login=%s, login_count=login_count+1 WHERE id=%s",
                        (datetime.now(timezone.utc), user["id"]),
                    )
                    conn.commit()
                    session["user"] = username
                    session["user_id"] = user["id"]
                    flash(f"Welcome back, {username}!", "success")
                    return redirect(url_for("dashboard"))
                else:
                    flash("Invalid username or password.", "error")
            conn.close()
        except Exception as e:
            flash(f"Database error: {e}", "error")

    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        email = request.form.get("email", "").strip()

        if not username or not password:
            flash("Username and password are required.", "error")
            return render_template("register.html")
        if len(password) < 6:
            flash("Password must be at least 6 characters.", "error")
            return render_template("register.html")

        try:
            conn = get_db()
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM users WHERE username=%s", (username,))
                if cur.fetchone():
                    flash("Username already exists.", "error")
                    return render_template("register.html")

                salt = secrets.token_hex(16)
                pw_hash = hash_password(password, salt)
                cur.execute(
                    "INSERT INTO users (username, password_hash, salt, email) VALUES (%s, %s, %s, %s)",
                    (username, pw_hash, salt, email),
                )
            conn.commit()
            conn.close()
            flash("Registration successful! Please log in.", "success")
            return redirect(url_for("login"))
        except Exception as e:
            flash(f"Registration failed: {e}", "error")

    return render_template("register.html")


@app.route("/dashboard")
def dashboard():
    if "user" not in session:
        return redirect(url_for("login"))

    info = {
        "hostname": os.uname().nodename,
        "db_host": DB_HOST,
        "db_name": DB_NAME,
        "time": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
    }

    # Get user list for admin
    users = []
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute("SELECT username, email, created_at, last_login, login_count FROM users ORDER BY id")
            users = cur.fetchall()
        conn.close()
    except Exception as e:
        flash(f"Could not load users: {e}", "error")

    return render_template("dashboard.html", user=session["user"], info=info, users=users)


@app.route("/health")
def health():
    """Health check endpoint for ALB target group."""
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
        conn.close()
        return {"status": "healthy", "db": "connected"}, 200
    except Exception as e:
        return {"status": "unhealthy", "db": str(e)}, 503


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("login"))


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5000, debug=False)
