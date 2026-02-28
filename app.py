from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3
import os
import json
from functools import wraps
import requests
import re

app = Flask(__name__)
app.secret_key = "change_this_to_a_random_secret"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "app.db")

# ----------------------------
# OLLAMA (LOCAL LLM EXTRACTION)
# ----------------------------
OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "llama3"
def extract_decision_details(question: str) -> dict:
    prompt = f"""You are an information extraction engine.
Return ONLY valid minified JSON. No explanations. No markdown. No code fences.

Schema:
{{"decision":string|null,"decision_type":string|null,"goal":string|null,"constraints":string[],"preferences":string[],"entities":string[],"time_horizon":string|null,"risk_level":string|null}}

Rules:
- decision = short description of the choice (e.g., "confess feelings", "choose laptop", "gate vs placements")
- decision_type = one of: ["relationship","career","education","purchase","health","finance","travel","other"]
- If uncertain, use "other".
- Do not guess missing values.
- constraints, preferences, and entities must ALWAYS be arrays (possibly empty).

Text: {question}"""
    try:
        r = requests.post(
            OLLAMA_URL,
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
            timeout=60
        )
        r.raise_for_status()
        text = (r.json().get("response") or "").strip()

        # First try: direct JSON
        try:
            parsed = json.loads(text)
        except Exception:
            # Fallback: extract first JSON object in the output
            m = re.search(r"\{.*\}", text, re.DOTALL)
            if not m:
                raise ValueError("No JSON found in model output")
            parsed = json.loads(m.group(0))

        # Safety defaults (never crash)
        if parsed.get("constraints") is None: parsed["constraints"] = []
        if parsed.get("preferences") is None: parsed["preferences"] = []
        if parsed.get("entities") is None: parsed["entities"] = []

        for k in ["decision_type", "goal", "time_horizon", "risk_level"]:
            if k not in parsed:
                parsed[k] = None

        return parsed

    except Exception as e:
        print("OLLAMA ERROR:", e)
        return {
            "decision_type": None,
            "goal": None,
            "constraints": [],
            "preferences": [],
            "entities": [],
            "time_horizon": None,
            "risk_level": None
        }


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
        extracted_context_json TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )
    """)

    # migration for older DBs
    try:
        cur.execute("ALTER TABLE decisions ADD COLUMN extracted_context_json TEXT")
    except sqlite3.OperationalError:
        pass

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
    CREATE TABLE IF NOT EXISTS criteria (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        decision_id INTEGER NOT NULL,
        name TEXT NOT NULL,
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

    return render_template("dashboard.html", name=session.get("user_name"), profile=profile)


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
# ROUTES: DECISION UI
# ----------------------------
@app.route("/decision", methods=["GET"])
@login_required
def decision():
    return render_template("decision.html")


# ----------------------------
# API: SAVE DECISION (called by decision.js)
# ----------------------------
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

    extracted = extract_decision_details(question)
    print("EXTRACTED RESULT:", extracted)

    extracted_json = json.dumps(extracted, ensure_ascii=False)

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        "INSERT INTO decisions (user_id, question, extracted_context_json) VALUES (?, ?, ?)",
        (session["user_id"], question, extracted_json)
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


# OPTIONAL: quick debug endpoint to see extracted JSON
@app.route("/decision/<int:decision_id>/debug", methods=["GET"])
@login_required
def decision_debug(decision_id):
    conn = get_db()
    row = conn.execute(
        "SELECT question, extracted_context_json FROM decisions WHERE id = ? AND user_id = ?",
        (decision_id, session["user_id"])
    ).fetchone()
    conn.close()

    if not row:
        return "Not found", 404

    return {
        "question": row["question"],
        "extracted": json.loads(row["extracted_context_json"] or "{}")
    }


if __name__ == "__main__":
    init_db()
    print("DB PATH:", DB_PATH)
    app.run(debug=True)