from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3
import os
import json
from functools import wraps
import requests
import re

from kb_loader import load_kb
from retriever import retrieve
from kb_score_apply import apply_default_scores

app = Flask(__name__)
app.secret_key = "change_this_to_a_random_secret"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "app.db")

# ----------------------------
# LOAD KB DOCS
# ----------------------------
KB_DOCS = load_kb("knowledgeBaseFiles")

# ----------------------------
# OLLAMA CONFIG
# ----------------------------
OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "llama3"


# ----------------------------
# LLM EXTRACTION
# ----------------------------
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

        try:
            parsed = json.loads(text)
        except Exception:
            m = re.search(r"\{.*\}", text, re.DOTALL)
            if not m:
                raise ValueError("No JSON found in model output")
            parsed = json.loads(m.group(0))

        if parsed.get("constraints") is None:
            parsed["constraints"] = []
        if parsed.get("preferences") is None:
            parsed["preferences"] = []
        if parsed.get("entities") is None:
            parsed["entities"] = []

        for k in ["decision", "decision_type", "goal", "time_horizon", "risk_level"]:
            if k not in parsed:
                parsed[k] = None

        return parsed

    except Exception as e:
        print("OLLAMA ERROR:", e)
        return {
            "decision": None,
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

    # Create decisions with kb_used_json included
    cur.execute("""
    CREATE TABLE IF NOT EXISTS decisions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        question TEXT NOT NULL,
        extracted_context_json TEXT,
        kb_used_json TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )
    """)

    # Migration safety for older DBs
    try:
        cur.execute("ALTER TABLE decisions ADD COLUMN extracted_context_json TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        cur.execute("ALTER TABLE decisions ADD COLUMN kb_used_json TEXT")
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
        importance INTEGER DEFAULT 3,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(decision_id) REFERENCES decisions(id)
    )
    """)

    try:
        cur.execute("ALTER TABLE criteria ADD COLUMN importance INTEGER DEFAULT 3")
    except sqlite3.OperationalError:
        pass

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
# API: SAVE DECISION + RAG + DEFAULT KB SCORING
# ----------------------------
@app.route("/decision/submit", methods=["POST"])
@login_required
def decision_submit():
    data = request.get_json(silent=True) or {}

    question = (data.get("question") or "").strip()
    options_list = data.get("options") or []
    criteria_list = data.get("criteria") or []  # list of {name, importance}

    if not question:
        return {"ok": False, "error": "Missing question"}, 400
    if len(options_list) < 2:
        return {"ok": False, "error": "Add at least 2 options"}, 400
    if len(criteria_list) < 1:
        return {"ok": False, "error": "Add at least 1 criterion"}, 400

    extracted = extract_decision_details(question)
    print("EXTRACTED RESULT:", extracted)

    decision_type = (extracted.get("decision_type") or "other").strip().lower()

    retrieved_docs = retrieve(KB_DOCS, decision_type, question, top_k=2)
    kb_used = [{
        "path": d["path"],
        "title": d.get("title", ""),
        "category": d.get("category", "")
    } for d in retrieved_docs]
    kb_used_json = json.dumps(kb_used, ensure_ascii=False)

    print("KB RETRIEVED:", [d.get("path") for d in retrieved_docs])
    print("KB SCORING MODES:", [d.get("scoring_mode") for d in retrieved_docs])

    extracted_json = json.dumps(extracted, ensure_ascii=False)

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        "INSERT INTO decisions (user_id, question, extracted_context_json, kb_used_json) VALUES (?, ?, ?, ?)",
        (session["user_id"], question, extracted_json, kb_used_json)
    )
    decision_id = cur.lastrowid

    # save options
    for opt in options_list:
        name = (str(opt) or "").strip()
        if not name:
            continue
        cur.execute(
            "INSERT INTO options (decision_id, name, source) VALUES (?, ?, ?)",
            (decision_id, name, "manual")
        )

    # save criteria
    for c in criteria_list:
        if isinstance(c, dict):
            name = (c.get("name") or "").strip()
            importance = int(c.get("importance") or 3)
        else:
            name = (str(c) or "").strip()
            importance = 3

        if not name:
            continue
        importance = max(1, min(5, importance))

        cur.execute(
            "INSERT INTO criteria (decision_id, name, importance) VALUES (?, ?, ?)",
            (decision_id, name, importance)
        )

    # ----------------------------
    # APPLY DEFAULT KB SCORING (fills option_scores)
    # ----------------------------
    options_rows = conn.execute(
        "SELECT id, name FROM options WHERE decision_id = ?",
        (decision_id,)
    ).fetchall()

    criteria_rows = conn.execute(
        "SELECT name, importance FROM criteria WHERE decision_id = ?",
        (decision_id,)
    ).fetchall()

    suggestions = []
    for d in retrieved_docs:
        if (d.get("scoring_mode") or "").strip().lower() == "default_role_based":
            suggestions = apply_default_scores(
                d,
                options=[{"id": r["id"], "name": r["name"]} for r in options_rows],
                criteria=[{"name": r["name"], "importance": r["importance"]} for r in criteria_rows],
            )
            if suggestions:
                break

    print("KB SCORE SUGGESTIONS:", suggestions)

    for s in suggestions:
        cur.execute(
            """INSERT INTO option_scores (option_id, criterion, score)
               VALUES (?, ?, ?)
               ON CONFLICT(option_id, criterion) DO UPDATE SET score=excluded.score""",
            (s["option_id"], s["criterion"], s["score"])
        )

    conn.commit()
    conn.close()

    return {"ok": True, "decision_id": decision_id, "kb_used": kb_used}


# ----------------------------
# DEBUG ENDPOINT
# ----------------------------
@app.route("/decision/<int:decision_id>/debug", methods=["GET"])
@login_required
def decision_debug(decision_id):
    conn = get_db()

    row = conn.execute(
        "SELECT question, extracted_context_json, kb_used_json FROM decisions WHERE id = ? AND user_id = ?",
        (decision_id, session["user_id"])
    ).fetchone()

    opts = conn.execute(
        "SELECT id, name FROM options WHERE decision_id = ?",
        (decision_id,)
    ).fetchall()

    crit = conn.execute(
        "SELECT name, importance FROM criteria WHERE decision_id = ?",
        (decision_id,)
    ).fetchall()

    scores = conn.execute(
        """SELECT os.option_id, o.name as option_name, os.criterion, os.score
           FROM option_scores os
           JOIN options o ON o.id = os.option_id
           WHERE o.decision_id = ?
           ORDER BY o.id, os.criterion""",
        (decision_id,)
    ).fetchall()

    conn.close()

    if not row:
        return "Not found", 404

    return {
        "question": row["question"],
        "extracted": json.loads(row["extracted_context_json"] or "{}"),
        "kb_used": json.loads(row["kb_used_json"] or "[]"),
        "options": [o["name"] for o in opts],
        "criteria": [{"name": c["name"], "importance": c["importance"]} for c in crit],
        "option_scores": [
            {"option_id": s["option_id"], "option_name": s["option_name"], "criterion": s["criterion"], "score": s["score"]}
            for s in scores
        ]
    }


if __name__ == "__main__":
    init_db()
    print("DB PATH:", DB_PATH)
    app.run(debug=True)