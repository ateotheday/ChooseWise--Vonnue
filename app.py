#from scoring import normalize_profile, rank_options
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

    # profiles table for saving the user profile data from the quiz
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

    cur.execute("""
    CREATE TABLE IF NOT EXISTS decisions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        question TEXT NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS options (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        decision_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        source TEXT DEFAULT 'manual',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(decision_id) REFERENCES decisions(id)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS option_scores (
        option_id INTEGER NOT NULL,
        criterion TEXT NOT NULL,
        score INTEGER NOT NULL,
        PRIMARY KEY(option_id, criterion),
        FOREIGN KEY(option_id) REFERENCES options(id)
    )
    """)
    #criteria table
    cur.execute("""
CREATE TABLE IF NOT EXISTS criteria (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(decision_id) REFERENCES decisions(id)
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

    if not user or not check_password_hash(user["password_hash"], password):
        conn.close()
        flash("Invalid email or password.")
        return render_template("login.html")

    session["user_id"] = user["id"]
    session["user_name"] = user["name"]

    prof = conn.execute(
        "SELECT 1 FROM profiles WHERE user_id = ?",
        (user["id"],)
    ).fetchone()
    conn.close()

    if prof:
        return redirect(url_for("dashboard"))
    return redirect(url_for("quiz"))
# New route to handle decision submission from decision UI
@app.route("/decision/submit", methods=["POST"])
@login_required
def decision_submit():
    data = request.get_json(silent=True) or {}

    question = (data.get("question") or "").strip()
    options_list = data.get("options") or []
    criteria_list = data.get("criteria") or []

    if not question:
        return {"ok": False, "error": "Missing question"}, 400
    if len(options_list) < 2:
        return {"ok": False, "error": "Add at least 2 options"}, 400
    if len(criteria_list) < 1:
        return {"ok": False, "error": "Add at least 1 criterion"}, 400

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        "INSERT INTO decisions (user_id, question) VALUES (?, ?)",
        (session["user_id"], question)
    )
    decision_id = cur.lastrowid

    for opt in options_list:
        cur.execute(
            "INSERT INTO options (decision_id, name, source) VALUES (?, ?, ?)",
            (decision_id, opt, "manual")
        )

    for c in criteria_list:
        cur.execute(
            "INSERT INTO criteria (decision_id, name) VALUES (?, ?)",
            (decision_id, c)
        )

    conn.commit()
    conn.close()

    return {"ok": True, "decision_id": decision_id}

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))


# ----------------------------
# ROUTES: PROTECTED
# ----------------------------
@app.route("/dashboard")
@login_required
def dashboard():
    conn = get_db()
    profile = conn.execute(
        "SELECT risk, budget, long_term, analytical, convenience FROM profiles WHERE user_id = ?",
        (session["user_id"],)
    ).fetchone()
    conn.close()

    return render_template(
        "dashboard.html",
        name=session.get("user_name"),
        profile=profile
    )


@app.route("/quiz", methods=["GET", "POST"])
@login_required
def quiz():
    conn = get_db()
    existing = conn.execute(
        "SELECT 1 FROM profiles WHERE user_id = ?",
        (session["user_id"],)
    ).fetchone()
    conn.close()

    if request.method == "GET":
        if existing:
            return redirect(url_for("dashboard"))
        return render_template("quiz.html")

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


# ----------------------------
# ROUTES: DECISION MAKING
# ----------------------------
print("DB PATH:", DB_PATH)

# UI-only route (single-page decision UI)
@app.route("/decision", methods=["GET"])
@login_required
def decision():
    return render_template("decision.html")


# --- Keeping your old scoring flow routes (not used by /decision now, but kept) ---

@app.route("/new-decision", methods=["GET", "POST"])
@login_required
def new_decision():
    if request.method == "GET":
        decision_question = session.get("decision_question")
        return render_template("new_decision.html", decision_question=decision_question)

    options = []
    for i in range(1, 4):
        name = (request.form.get(f"name{i}") or "").strip()
        if not name:
            continue

        scores = {
            "risk": int(request.form.get(f"risk{i}", 0)),
            "budget": int(request.form.get(f"budget{i}", 0)),
            "long_term": int(request.form.get(f"long_term{i}", 0)),
            "analytical": int(request.form.get(f"analytical{i}", 0)),
            "convenience": int(request.form.get(f"convenience{i}", 0)),
        }

        if any(v < 1 or v > 10 for v in scores.values()):
            flash("Option scores must be between 1 and 10.")
            decision_question = session.get("decision_question")
            return render_template("new_decision.html", decision_question=decision_question)

        options.append({"name": name, "scores": scores})

    if len(options) < 2:
        flash("Please enter at least 2 options.")
        decision_question = session.get("decision_question")
        return render_template("new_decision.html", decision_question=decision_question)

    session["current_options"] = options
    return redirect(url_for("evaluate_dynamic"))


@app.route("/evaluate-dynamic")
@login_required
def evaluate_dynamic():
    conn = get_db()
    profile = conn.execute(
        "SELECT risk, budget, long_term, analytical, convenience FROM profiles WHERE user_id = ?",
        (session["user_id"],)
    ).fetchone()
    conn.close()

    if not profile:
        return redirect(url_for("quiz"))

    options = session.get("current_options")
    if not options:
        flash("No options found. Create a decision first.")
        return redirect(url_for("new_decision"))

    weights = normalize_profile(profile)
    ranked = rank_options(options, weights)
    decision_question = session.get("decision_question")

    return render_template(
        "results.html",
        weights=weights,
        ranked=ranked,
        decision_question=decision_question
    )


if __name__ == "__main__":
    init_db()
    app.run(debug=True)