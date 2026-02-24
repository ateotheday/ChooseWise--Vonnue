from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3
import os
from functools import wraps

app = Flask(__name__)
app.secret_key = "change_this_to_a_random_secret"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "app.db")


# ----------------------------
# DATABASE HELPERS
# ----------------------------
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)
#profiles tble for saving the user profile data from the quiz
    cur.execute("""
CREATE TABLE IF NOT EXISTS profiles (
    user_id INTEGER PRIMARY KEY,
    risk INTEGER,
    budget INTEGER,
    long_term INTEGER,
    analytical INTEGER,
    convenience INTEGER,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(user_id) REFERENCES users(id)
)
""")

    conn.commit()
    conn.close()


# ----------------------------
# AUTH DECORATOR
# ----------------------------
def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapper


# ----------------------------
# ROUTES: PUBLIC
# ----------------------------
@app.route("/")
def home():
    return render_template("index.html")


# ----------------------------
# ROUTES: AUTH
# ----------------------------
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "GET":
        return render_template("register.html")

    name = (request.form.get("name") or "").strip()
    email = (request.form.get("email") or "").strip().lower()
    password = request.form.get("password") or ""
    confirm = request.form.get("confirm_password") or ""

    if not name or not email or not password:
        flash("Please fill all fields.")
        return render_template("register.html")

    if password != confirm:
        flash("Passwords do not match.")
        return render_template("register.html")

    password_hash = generate_password_hash(password)

    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
            (name, email, password_hash)
        )
        conn.commit()
        conn.close()
    except sqlite3.IntegrityError:
        flash("Email already registered. Please log in.")
        return redirect(url_for("login"))

    flash("Account created! Please log in.")
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html")

    email = (request.form.get("email") or "").strip().lower()
    password = request.form.get("password") or ""

    conn = get_db()
    user = conn.execute(
        "SELECT id, name, email, password_hash FROM users WHERE email = ?",
        (email,)
    ).fetchone()
    conn.close()

    if not user or not check_password_hash(user["password_hash"], password):
        flash("Invalid email or password.")
        return render_template("login.html")

    session["user_id"] = user["id"]
    session["user_name"] = user["name"]
    return redirect(url_for("quiz"))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))
# ----------------------------
# ROUTES: PROTECTED
# ---------------------------
@app.route("/dashboard")
@login_required
def dashboard():
    return render_template("dashboard.html", name=session.get("user_name"))

@app.route("/quiz", methods=["GET", "POST"])
@login_required
def quiz():
    if request.method == "POST":
        risk = int(request.form.get("risk", 0))
        budget = int(request.form.get("budget", 0))
        long_term = int(request.form.get("long_term", 0))
        analytical = int(request.form.get("analytical", 0))
        convenience = int(request.form.get("convenience", 0))

        if any(v < 1 or v > 5 for v in [risk, budget, long_term, analytical, convenience]):
            flash("Please select values between 1 and 5 for all questions.")
            return render_template("quiz.html")

        conn = get_db()
        conn.execute("""
            INSERT INTO profiles (user_id, risk, budget, long_term, analytical, convenience)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                risk=excluded.risk,
                budget=excluded.budget,
                long_term=excluded.long_term,
                analytical=excluded.analytical,
                convenience=excluded.convenience
        """, (session["user_id"], risk, budget, long_term, analytical, convenience))
        conn.commit()
        conn.close()

        return redirect(url_for("dashboard"))

    return render_template("quiz.html")
print("DB PATH:", DB_PATH)
if __name__ == "__main__":
    init_db()
    app.run(debug=True)