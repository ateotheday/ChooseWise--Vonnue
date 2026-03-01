from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3
import os
import json
from functools import wraps
import requests
import re
import time

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

EXTRACT_TIMEOUT = 180
MATRIX_TIMEOUT = 300

EXTRACT_RETRIES = 2
MATRIX_RETRIES = 2


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def guess_decision_type(question: str) -> str:
    q = (question or "").lower()
    if any(k in q for k in ["job", "government", "govt", "private", "career", "placement", "internship", "salary", "offer"]):
        return "career"
    if any(k in q for k in ["college", "mtech", "gate", "degree", "course", "study", "iit", "ms ", "mba"]):
        return "education"
    if any(k in q for k in ["laptop", "phone", "buy", "purchase", "price", "budget", "specs", "ram", "ssd"]):
        return "purchase"
    if any(k in q for k in ["trip", "travel", "vacation", "itinerary"]):
        return "travel"
    if any(k in q for k in ["investment", "stocks", "mutual fund", "sip", "loan", "emi", "savings"]):
        return "finance"
    if any(k in q for k in ["health", "diet", "workout", "medicine", "sleep"]):
        return "health"
    return "other"


def pick_scoring_docs(retrieved_docs, question: str, max_docs=2):
    if not retrieved_docs:
        return []

    q = (question or "").lower()
    scored = []

    for d in retrieved_docs:
        path = (d.get("path") or "").lower()
        title = (d.get("title") or "").lower()
        cat = (d.get("category") or "").lower()
        text = (d.get("text") or "").lower()
        hint = " ".join([path, title, cat])

        score = 0

        if any(k in q for k in ["govt", "government", "private"]):
            if "govt_vs_private" in hint or ("government" in hint and "private" in hint):
                score += 120

        kw = []
        if "stability" in q or "security" in q:
            kw += ["stability", "security", "job security"]
        if "salary" in q or "pay" in q or "package" in q:
            kw += ["salary", "pay", "compensation", "income"]
        if "growth" in q or "career" in q:
            kw += ["growth", "career", "promotion"]
        if "pressure" in q or "stress" in q:
            kw += ["pressure", "stress", "work pressure"]

        for w in kw:
            if w in text:
                score += 12

        score += min(len(text) // 1000, 5)
        scored.append((score, d))

    scored.sort(key=lambda x: x[0], reverse=True)
    picked = [d for s, d in scored if s > 0][:max_docs]
    return picked or [retrieved_docs[0]]


def safe_json_from_text(text: str) -> dict:
    t = (text or "").strip()
    try:
        return json.loads(t)
    except Exception:
        m = re.search(r"\{.*\}", t, re.DOTALL)
        if not m:
            return {}
        try:
            return json.loads(m.group(0))
        except Exception:
            return {}


def ollama_generate(prompt: str, timeout: int, retries: int = 0):
    last_err = None
    for attempt in range(retries + 1):
        try:
            r = requests.post(
                OLLAMA_URL,
                json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
                timeout=timeout
            )
            r.raise_for_status()
            return (r.json().get("response") or "").strip()
        except Exception as e:
            last_err = e
            time.sleep(0.8 * (attempt + 1))
    raise last_err


def extract_decision_details(question: str) -> dict:
    prompt = f"""You are an information extraction engine.
Return ONLY valid minified JSON. No explanations. No markdown. No code fences.

Schema:
{{"decision":string|null,"decision_type":string|null,"goal":string|null,"constraints":string[],"preferences":string[],"entities":string[],"time_horizon":string|null,"risk_level":string|null}}

Rules:
- decision = short description of the choice (can be the question rephrased)
- decision_type = one of: ["relationship","career","education","purchase","health","finance","travel","other"]
- If uncertain, use "other".
- constraints, preferences, and entities must ALWAYS be arrays (possibly empty).

Text: {question}"""

    try:
        text = ollama_generate(prompt, timeout=EXTRACT_TIMEOUT, retries=EXTRACT_RETRIES)
        parsed = safe_json_from_text(text)

        if parsed.get("constraints") is None:
            parsed["constraints"] = []
        if parsed.get("preferences") is None:
            parsed["preferences"] = []
        if parsed.get("entities") is None:
            parsed["entities"] = []

        for k in ["decision", "decision_type", "goal", "time_horizon", "risk_level"]:
            if k not in parsed:
                parsed[k] = None

        if not parsed.get("decision_type"):
            parsed["decision_type"] = guess_decision_type(question)

        if not parsed.get("decision"):
            parsed["decision"] = question.strip()

        if not parsed.get("goal"):
            parsed["goal"] = "Choose the best option based on the user's priorities."

        return parsed

    except Exception as e:
        print("OLLAMA ERROR (extract):", e)
        return {
            "decision": question.strip(),
            "decision_type": guess_decision_type(question),
            "goal": "Choose the best option based on the user's priorities.",
            "constraints": [],
            "preferences": [],
            "entities": [],
            "time_horizon": None,
            "risk_level": None
        }


def build_kb_context(kb_docs: list[dict], per_doc_chars: int = 900, max_total_chars: int = 1800) -> str:
    chunks = []
    total = 0
    for d in kb_docs:
        title = d.get("title", "")
        cat = d.get("category", "")
        txt = (d.get("text") or "").strip()
        piece = f"[{cat}] {title}\n{txt[:per_doc_chars]}"
        if total + len(piece) > max_total_chars:
            break
        chunks.append(piece)
        total += len(piece)
    return "\n\n---\n\n".join(chunks)


def keyword_fallback_scores(question: str, options: list[str], criteria: list[str]) -> list[dict]:
    q = (question or "").lower()

    criterion_keywords = {
        "job stability": {
            "government job": ["permanent", "pension", "job security", "stable", "security"],
            "private job": ["layoff", "variable", "performance", "unstable", "switch"]
        },
        "salary": {
            "government job": ["fixed", "pay scale", "allowance"],
            "private job": ["high", "bonus", "package", "hike"]
        },
        "growth": {
            "government job": ["slow", "seniority"],
            "private job": ["growth", "promotion", "learning", "skill"]
        },
        "work life balance": {
            "government job": ["hours", "balance", "leave"],
            "private job": ["pressure", "deadline", "overtime"]
        }
    }

    out = []
    for o in options:
        o_l = o.lower()
        for c in criteria:
            c_l = c.lower()

            score = 3
            reason = "Insufficient KB evidence"
            found = False

            if c_l in criterion_keywords:
                mapping = criterion_keywords[c_l]
                for opt_key, kws in mapping.items():
                    if opt_key in o_l:
                        hits = sum(1 for kw in kws if kw in q)
                        if hits >= 2:
                            score = 4
                            reason = f"Matched keywords in question for {c}: {', '.join([kw for kw in kws if kw in q])}"
                        elif hits == 1:
                            score = 3
                            reason = f"Matched keyword in question for {c}: {', '.join([kw for kw in kws if kw in q])}"
                        else:
                            score = 3
                            reason = "Insufficient KB evidence"
                        found = True
                        break

            if not found:
                score = 3
                reason = "Insufficient KB evidence"

            out.append({"option": o, "criterion": c, "score": score, "reason": reason})
    return out


def llm_fill_matrix(question: str, options: list[str], criteria: list[str], kb_docs: list[dict]) -> dict:
    kb_context = build_kb_context(kb_docs)

    prompt = f"""
You are a scoring assistant for a transparent decision-support system.

Use ONLY the provided KB context. Do NOT use external knowledge.
Return ONLY valid minified JSON. No markdown.

IMPORTANT RULES:
- Use option names EXACTLY as they appear in the Options array (character-for-character).
- Use criterion names EXACTLY as they appear in the Criteria array (character-for-character).
- Output MUST include every pair (option, criterion). That means len(Options) * len(Criteria) items.

Score scale: 1 (worst) to 5 (best).

Schema:
{{"scores":[{{"option":string,"criterion":string,"score":int,"reason":string}}]}}

Question: {question}
Options: {options}
Criteria: {criteria}

KB context:
{kb_context}
""".strip()

    try:
        text = ollama_generate(prompt, timeout=MATRIX_TIMEOUT, retries=MATRIX_RETRIES)
        print("KB CONTEXT LEN:", len(kb_context))
        print("LLM RAW OUTPUT (first 800):", text[:800])

        parsed = safe_json_from_text(text)
        if not isinstance(parsed, dict):
            return {"scores": []}
        if "scores" not in parsed:
            parsed["scores"] = []
        return parsed

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


def compute_ranking(options, criteria, option_scores):
    crit_w = {c["name"]: int(c.get("importance") or 3) for c in criteria}
    by_option = {}
    for s in option_scores:
        on = s["option_name"]
        cn = s["criterion"]
        sc = int(s["score"])
        by_option.setdefault(on, {})
        by_option[on][cn] = sc

    totals = []
    for opt in options:
        name = opt["name"]
        total = 0
        weight_sum = 0

        for cn, w in crit_w.items():
            weight_sum += w
            sc = by_option.get(name, {}).get(cn, 3)
            total += sc * w

        if weight_sum == 0:
            weight_sum = 1

        totals.append({
            "option": name,
            "weighted_score": total,
            "weight_sum": weight_sum,
            "normalized_0_100": round((total / (weight_sum * 5)) * 100, 2)
        })

    totals.sort(key=lambda x: x["weighted_score"], reverse=True)
    return totals


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
    decision_type = (extracted.get("decision_type") or guess_decision_type(question)).strip().lower()

    print("EXTRACTED RESULT:", extracted)
    print("DECISION TYPE:", decision_type)

    retrieved_docs = retrieve(KB_DOCS, decision_type, question, top_k=3)
    kb_used = [{
        "path": d.get("path", ""),
        "title": d.get("title", ""),
        "category": d.get("category", "")
    } for d in retrieved_docs]
    kb_used_json = json.dumps(kb_used, ensure_ascii=False)

    print("KB RETRIEVED:", [d.get("path") for d in retrieved_docs])

    scoring_docs = pick_scoring_docs(retrieved_docs, question, max_docs=2)
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

    if not matrix:
        matrix = keyword_fallback_scores(question, opt_names, crit_names)

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

    # return also the url so frontend can redirect
    return {"ok": True, "decision_id": decision_id, "kb_used": kb_used, "result_url": f"/decision/{decision_id}/result"}


@app.route("/decision/<int:decision_id>/debug", methods=["GET"])
@login_required
def decision_debug(decision_id):
    conn = get_db()

    row = conn.execute(
        "SELECT question, extracted_context_json, kb_used_json FROM decisions WHERE id = ? AND user_id = ?",
        (decision_id, session["user_id"])
    ).fetchone()

    if not row:
        conn.close()
        return "Not found", 404

    opts = conn.execute(
        "SELECT id, name FROM options WHERE decision_id = ? ORDER BY id",
        (decision_id,)
    ).fetchall()

    crit = conn.execute(
        "SELECT name, importance FROM criteria WHERE decision_id = ? ORDER BY id",
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

    options_list = [{"id": o["id"], "name": o["name"]} for o in opts]
    criteria_list = [{"name": c["name"], "importance": c["importance"]} for c in crit]
    score_list = [{"option_name": s["option_name"], "criterion": s["criterion"], "score": s["score"]} for s in scores]

    ranking = compute_ranking(options_list, criteria_list, score_list)

    return jsonify({
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
        ],
        "ranking": ranking
    })


# ✅✅✅ NEW RESULT PAGE ROUTE
@app.route("/decision/<int:decision_id>/result", methods=["GET"])
@login_required
def decision_result(decision_id):
    conn = get_db()

    d = conn.execute(
        "SELECT id, question, created_at, kb_used_json FROM decisions WHERE id=? AND user_id=?",
        (decision_id, session["user_id"])
    ).fetchone()

    if not d:
        conn.close()
        return "Not found", 404

    opts = conn.execute(
        "SELECT id, name FROM options WHERE decision_id=? ORDER BY id",
        (decision_id,)
    ).fetchall()

    crit = conn.execute(
        "SELECT name, importance FROM criteria WHERE decision_id=? ORDER BY id",
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

    options_list = [{"id": o["id"], "name": o["name"]} for o in opts]
    criteria_list = [{"name": c["name"], "importance": c["importance"]} for c in crit]
    score_list = [{"option_name": s["option_name"], "criterion": s["criterion"], "score": s["score"]} for s in scores]
    ranking = compute_ranking(options_list, criteria_list, score_list)

    score_map = {}
    for s in scores:
        score_map[(_norm(s["option_name"]), _norm(s["criterion"]))] = int(s["score"])

    reason_map = {}
    for r in reasons:
        reason_map[(_norm(r["option_name"]), _norm(r["criterion"]))] = r["reason"]

    ranked = []
    for r in ranking:
        on = r["option"]
        breakdown = []
        for c in criteria_list:
            cn = c["name"]
            w = int(c.get("importance") or 3)
            sc = score_map.get((_norm(on), _norm(cn)), 3)
            rs = reason_map.get((_norm(on), _norm(cn)), "Insufficient KB evidence")
            breakdown.append({
                "criteria": cn,
                "importance": w,
                "score": sc,
                "weighted": sc * w,
                "reason": rs
            })

        ranked.append({
            "name": on,
            "normalized_0_100": r["normalized_0_100"],
            "weighted_score": r["weighted_score"],
            "breakdown": breakdown
        })

    kb_used = []
    try:
        kb_used = json.loads(d["kb_used_json"] or "[]")
    except:
        kb_used = []

    decision = {
        "id": d["id"],
        "question": d["question"],
        "created_at": d["created_at"],
        "kb_used": kb_used
    }

    return render_template("result.html", decision=decision, ranked=ranked)


if __name__ == "__main__":
    init_db()
    app.run(debug=True)