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

app = Flask(__name__)
app.secret_key = "change_this_to_a_random_secret"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "app.db")

print("RUNNING THIS FILE:", __file__)
print("DB PATH:", DB_PATH)

KB_DOCS = load_kb("knowledgeBaseFiles")

OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "llama3"


def _norm(s):
    return re.sub(r"\s+", " ", (s or "").strip().lower())


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
        print("OLLAMA ERROR (extract):", e)
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


def llm_fill_matrix(question: str, options: list[str], criteria: list[str], kb_docs: list[dict]) -> dict:
    kb_context = "\n\n---\n\n".join(
        [f"[{d.get('category','')}] {d.get('title','')}\n{(d.get('text') or '')[:900]}" for d in kb_docs]
    )

    prompt = f"""
You are a scoring assistant for a transparent decision-support system.

Use ONLY the provided KB context. Do NOT use external knowledge.
Return ONLY valid minified JSON. No markdown.

IMPORTANT RULES:
- Use option names EXACTLY as they appear in the Options array (character-for-character).
- Use criterion names EXACTLY as they appear in the Criteria array (character-for-character).
- Output MUST include every pair (option, criterion). That means len(Options) * len(Criteria) items.

Score scale: 1 (worst) to 5 (best).
If KB does not provide enough evidence, return score 3 and reason "Insufficient KB evidence".

Schema:
{{"scores":[{{"option":string,"criterion":string,"score":int,"reason":string}}]}}

Question: {question}
Options: {options}
Criteria: {criteria}

KB context:
{kb_context}
""".strip()

    try:
        r = requests.post(
            OLLAMA_URL,
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
            timeout=180
        )
        r.raise_for_status()
        text = (r.json().get("response") or "").strip()

        print("KB CONTEXT LEN:", len(kb_context))
        print("LLM RAW OUTPUT (first 1200):", text[:1200])

        m = re.search(r"\{.*\}", text, re.DOTALL)
        if not m:
            print("LLM RAW OUTPUT (no JSON found):", text[:1200])
            return {"scores": []}

        return json.loads(m.group(0))

    except Exception as e:
        print("OLLAMA ERROR (matrix):", e)
        return {"scores": []}


def validate_matrix(llm_out: dict, options: list[str], criteria: list[str]) -> list[dict]:
    wanted = {(_norm(o), _norm(c)) for o in options for c in criteria}
    out = []

    for item in (llm_out.get("scores") or []):
        opt = (item.get("option") or "").strip()
        crit = (item.get("criterion") or "").strip()
        score = item.get("score")
        reason = (item.get("reason") or "").strip()

        key = (_norm(opt), _norm(crit))
        if key not in wanted:
            continue

        if not isinstance(score, int) or score < 1 or score > 5:
            score = 3
        if not reason:
            reason = "Insufficient KB evidence"

        out.append({"option": opt, "criterion": crit, "score": score, "reason": reason})

    present = {(_norm(x["option"]), _norm(x["criterion"])) for x in out}

    for o in options:
        for c in criteria:
            if (_norm(o), _norm(c)) not in present:
                out.append({"option": o, "criterion": c, "score": 3, "reason": "Insufficient KB evidence"})

    return out


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
        kb_used_json TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )
    """)

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

    cur.execute("""
    CREATE TABLE IF NOT EXISTS option_score_reasons (
        option_id INTEGER NOT NULL,
        criterion TEXT NOT NULL,
        reason TEXT NOT NULL,
        PRIMARY KEY(option_id, criterion),
        FOREIGN KEY(option_id) REFERENCES options(id)
    )
    """)

    conn.commit()
    conn.close()


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapper


@app.route("/")
def home():
    return render_template("index.html")


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

    prof = conn.execute("SELECT 1 FROM profiles WHERE user_id = ?", (user["id"],)).fetchone()
    conn.close()

    if prof:
        return redirect(url_for("dashboard"))
    return redirect(url_for("quiz"))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))


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
    existing = conn.execute("SELECT 1 FROM profiles WHERE user_id = ?", (session["user_id"],)).fetchone()
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


@app.route("/decision", methods=["GET"])
@login_required
def decision():
    return render_template("decision.html")


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
    decision_type = (extracted.get("decision_type") or "other").strip().lower()
    print("EXTRACTED RESULT:", extracted)

    retrieved_docs = retrieve(KB_DOCS, decision_type, question, top_k=3)
    kb_used = [{
        "path": d.get("path", ""),
        "title": d.get("title", ""),
        "category": d.get("category", "")
    } for d in retrieved_docs]
    kb_used_json = json.dumps(kb_used, ensure_ascii=False)

    print("KB RETRIEVED:", [d.get("path") for d in retrieved_docs])

    scoring_docs = retrieved_docs[:1]
    print("SCORING DOCS:", [d.get("path") for d in scoring_docs])

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        "INSERT INTO decisions (user_id, question, extracted_context_json, kb_used_json) VALUES (?, ?, ?, ?)",
        (session["user_id"], question, json.dumps(extracted, ensure_ascii=False), kb_used_json)
    )
    decision_id = cur.lastrowid

    for opt in options_list:
        name = (str(opt) or "").strip()
        if not name:
            continue
        cur.execute(
            "INSERT INTO options (decision_id, name, source) VALUES (?, ?, ?)",
            (decision_id, name, "manual")
        )

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

    options_rows = conn.execute(
        "SELECT id, name FROM options WHERE decision_id = ?",
        (decision_id,)
    ).fetchall()

    criteria_rows = conn.execute(
        "SELECT name, importance FROM criteria WHERE decision_id = ?",
        (decision_id,)
    ).fetchall()

    opt_names = [r["name"] for r in options_rows]
    crit_names = [r["name"] for r in criteria_rows]

    llm_out = llm_fill_matrix(question, opt_names, crit_names, scoring_docs)
    matrix = validate_matrix(llm_out, opt_names, crit_names)

    name_to_id = {_norm(r["name"]): r["id"] for r in options_rows}

    for mrow in matrix:
        oid = name_to_id.get(_norm(mrow["option"]))
        if not oid:
            continue

        cur.execute(
            """INSERT INTO option_scores (option_id, criterion, score)
               VALUES (?, ?, ?)
               ON CONFLICT(option_id, criterion) DO UPDATE SET score=excluded.score""",
            (oid, mrow["criterion"], mrow["score"])
        )

        cur.execute(
            """INSERT INTO option_score_reasons (option_id, criterion, reason)
               VALUES (?, ?, ?)
               ON CONFLICT(option_id, criterion) DO UPDATE SET reason=excluded.reason""",
            (oid, mrow["criterion"], mrow["reason"])
        )

    conn.commit()
    conn.close()

    return {"ok": True, "decision_id": decision_id, "kb_used": kb_used}


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

    reasons = conn.execute(
        """SELECT r.option_id, o.name as option_name, r.criterion, r.reason
           FROM option_score_reasons r
           JOIN options o ON o.id = r.option_id
           WHERE o.decision_id = ?
           ORDER BY o.id, r.criterion""",
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
        ],
        "score_reasons": [
            {"option_id": r["option_id"], "option_name": r["option_name"], "criterion": r["criterion"], "reason": r["reason"]}
            for r in reasons
        ]
    }


if __name__ == "__main__":
    init_db()
    app.run(debug=True)