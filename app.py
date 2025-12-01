import os
import io
import base64
import qrcode
from functools import wraps
from datetime import datetime, date, timedelta
from urllib.parse import urlparse, urljoin
from flask import Response
import csv
from io import StringIO
from huggingface_hub import InferenceClient

from flask import (
    Flask,
    request,
    jsonify,
    session,
    render_template,
    redirect,
    url_for,
)
from dotenv import load_dotenv
from pymongo import MongoClient
from bson.objectid import ObjectId
import bcrypt
import pyotp

from plaid_client import (
    get_current_balances,
    get_recent_transactions,
    create_sandbox_access_token,
)

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "templates"),
    static_folder=os.path.join(BASE_DIR, "static"),
)

SECRET_KEY = os.getenv("BUDGETMIND_SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError("BUDGETMIND_SECRET_KEY is not set in .env")
app.secret_key = SECRET_KEY

MONGO_URI = os.getenv("MONGO_URI")
if not MONGO_URI:
    raise RuntimeError("MONGO_URI is not set in .env")

HF_API_KEY = os.getenv("AI_API_KEY")
if not HF_API_KEY:
    raise RuntimeError("AI_API_KEY is not set in .env")

HF_MODEL_ID = "Qwen/Qwen2.5-7B-Instruct-1M"

hf_client = InferenceClient(
    model=HF_MODEL_ID,
    token=HF_API_KEY,
)

mongo_client = MongoClient(MONGO_URI)
db = mongo_client.get_database("BudgetMindAI")
users_col = db.get_collection("users")
entries_col = db.get_collection("entries")
profile_pics_col = db.get_collection("profilepics")
bank_accounts_col = db.get_collection("bank_account_connected")
notes_col = db.get_collection("notes")
clients_col = db.get_collection("clients")
notifications_col = db.get_collection("notifications")
advisor_notes_col = db.get_collection("advisor_notes")
transactions_col = db.get_collection("transactions")
flagged_col = db.get_collection("flagged_transactions")
compliance_settings_col = db.get_collection("compliance_settings")
audit_logs_col = db.get_collection("audit_logs")
financially_vulnerable_col = db.get_collection("financially_vulnerable_users")




def resolve_category(raw_list):
    if not raw_list or not isinstance(raw_list, list):
        return "Other"
    raw = raw_list[0].lower()
    if "uber" in raw or "lyft" in raw:
        return "Transport"
    if "mcdonald" in raw or "starbucks" in raw:
        return "Food & Drink"
    if "pay" in raw or "payment" in raw:
        return "Bills"
    if "airlines" in raw or "flight" in raw:
        return "Travel"
    if "deposit" in raw or "credit" in raw:
        return "Income"
    return raw_list[0].title()


DEFAULT_SPENDING_LIMIT = 1000.0


def recalc_spending_flag_for_user(user_id: str):
    try:
        user_obj_id = ObjectId(user_id)
    except Exception:
        return
    user = users_col.find_one({"_id": user_obj_id})
    if not user:
        return
    total_expense = 0.0
    for e in entries_col.find({"user_id": user_id}):
        if str(e.get("type", "")).lower() == "expense":
            try:
                total_expense += float(e.get("amount", 0))
            except (TypeError, ValueError):
                continue
    try:
        spending_limit = float(user.get("spending_limit", DEFAULT_SPENDING_LIMIT))
    except (TypeError, ValueError):
        spending_limit = DEFAULT_SPENDING_LIMIT
    is_over = total_expense > spending_limit
    updates = {"is_flagged": is_over}
    if is_over:
        note_text = "Spending limit exceeded"
        notes = user.get("notes", [])
        has_note = any(
            isinstance(n, dict) and n.get("message") == note_text
            for n in notes
        )
        if not has_note:
            notes.append({
                "message": note_text,
                "created_at": datetime.utcnow(),
            })
        updates["notes"] = notes
    users_col.update_one({"_id": user_obj_id}, {"$set": updates})


def normalize_role(role):
    if not role:
        return ""
    role = str(role).strip().lower()
    if role in ["financialadvisor", "financial advisor", "advisor", "fa"]:
        return "Financial Advisor"
    if role in ["averageuser", "average user", "user"]:
        return "Average User"
    if role in ["complianceregulator", "compliance regulator", "regulator"]:
        return "Compliance Regulator"
    return role.title()


def _is_safe_url(target: str) -> bool:
    if not target:
        return False
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    return test_url.scheme in ("http", "https") and ref_url.netloc == test_url.netloc


def login_required(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if session.get("user_id"):
            return view_func(*args, **kwargs)
        next_url = request.full_path if request.query_string else request.path
        return redirect(url_for("login_page", next=next_url))
    return wrapped
#audit logs
def write_audit_log(action, details=None, status=None):
    """
    Generic audit logger. Call this from routes, or use the after_request
    hook below to automatically log all /api/* calls.

    action: short string describing what happened (e.g. "HTTP_API_CALL", "LOGIN_FAILED")
    details: optional dict with extra info
    status: HTTP status code (int)
    """
    try:
        doc = {
            "timestamp": datetime.utcnow(),
            "user_id": session.get("user_id"),
            "role": session.get("role"),
            "action": action,
            "ip": request.remote_addr,
            "path": request.path,
            "method": request.method,
            "status": status,
            "details": details or {},
        }
        audit_logs_col.insert_one(doc)
    except Exception as e:
        # Never break the main app just because logging failed
        print("AUDIT LOG ERROR:", e)

@app.after_request
def audit_after_request(response):
    """
    Automatically write an audit log entry for every /api/* request.
    This gives you a full audit trail without touching each route.
    """
    try:
        path = request.path or ""
        # Only log API calls, skip static/assets
        if path.startswith("/api/"):
            payload = None
            if request.method in ("POST", "PUT", "PATCH"):
                # Don't crash if body isn't JSON
                payload = request.get_json(silent=True)

            write_audit_log(
                action="HTTP_API_CALL",
                details={
                    "query": request.args.to_dict(),
                    "json": payload,
                },
                status=response.status_code,
            )
    except Exception as e:
        print("AUDIT AFTER_REQUEST ERROR:", e)

    return response


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    if not password or not hashed:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


def find_user_by_identifier(identifier: str):
    ident = (identifier or "").strip().lower()
    if not ident:
        return None
    return users_col.find_one({
        "$or": [{"email": ident}, {"username": ident}]
    })


def _compute_total_balance(balances_payload: dict) -> float:
    total = 0.0
    for acct in balances_payload.get("accounts", []):
        bal = acct.get("balances", {}).get("current")
        if bal is not None:
            try:
                total += float(bal)
            except (TypeError, ValueError):
                continue
    return total


def _classify_direction(name: str, category: str | None) -> bool:
    label = f"{name or ''} {category or ''}".lower()
    income_keywords = ["payroll", "deposit", "credit", "refund", "interest", "intrst"]
    return any(k in label for k in income_keywords)

def _get_advisor_client_link(client_link_id: str, require_accepted: bool = True):
    """
    Look up the clients_col document (advisor <-> client link) for the
    currently logged-in advisor.

    If require_accepted is True, we only return links where the client
    has granted permission (status == 'Accepted').

    Returns:
        (link_doc, None) on success
        (None, (response, http_status)) on error
    """
    if session.get("role") != "Financial Advisor":
        return None, (jsonify({"ok": False, "message": "Unauthorized"}), 403)

    advisor_id_str = session.get("user_id")
    try:
        advisor_id = ObjectId(advisor_id_str)
        link_obj_id = ObjectId(client_link_id)
    except Exception:
        return None, (jsonify({"ok": False, "message": "Invalid id"}), 400)

    query = {"_id": link_obj_id, "advisor_id": advisor_id}
    if require_accepted:
        # Only allow if the client has accepted the advisor’s request
        query["status"] = "Accepted"

    link = clients_col.find_one(query)
    if not link:
        msg = "Client not found or permission not granted" if require_accepted else "Client not found"
        return None, (jsonify({"ok": False, "message": msg}), 404)

    return link, None


def _simplify_transactions(tx_payload: dict):
    result = []
    for tx in tx_payload.get("transactions", []):
        raw_date = tx.get("date")
        if isinstance(raw_date, (date, datetime)):
            date_str = raw_date.isoformat()
        else:
            date_str = str(raw_date)
        category = None
        cat_list = tx.get("category") or []
        if isinstance(cat_list, list) and len(cat_list) > 0:
            category = " / ".join(cat_list)
        if not category:
            pfc = tx.get("personal_finance_category", {})
            category = (
                pfc.get("primary")
                or pfc.get("detailed")
                or None
            )
        if not category:
            category = "Uncategorized"
        result.append({
            "date": date_str,
            "name": tx.get("name"),
            "category": category,
            "amount": tx.get("amount"),
            "iso_currency_code": tx.get("iso_currency_code"),
            "transaction_id": tx.get("transaction_id"),
        })
    return result


@app.route("/api/compliance/save_settings", methods=["POST"])
@login_required
def api_compliance_save_settings():
    if session.get("role") != "Compliance Regulator":
        return jsonify({"ok": False, "message": "Unauthorized"}), 403

    data = request.get_json() or {}

    compliance_settings_col.update_one(
        {"_id": "global"},   # single global compliance policy
        {"$set": {
            "enable_data_masking": data.get("enable_data_masking", False),
            "enable_ip_logging": data.get("enable_ip_logging", False),
            "auto_anonymize": data.get("auto_anonymize", False),
            "notify_critical": data.get("notify_critical", False),
            "track_admin": data.get("track_admin", False),
            "retention_days": int(data.get("retention_days", 90)),
            "updated_at": datetime.utcnow()
        }},
        upsert=True
    )

    return jsonify({"ok": True})

@app.route("/api/compliance/financially_vulnerable/scan", methods=["POST"])
@login_required
def api_financially_vulnerable_scan():
    """
    Scan all Plaid-connected users and determine whether they are
    financially vulnerable based on net income remaining.

    Rules (over a given time window):
      - net = income - expenses
      - percent_left = (net / income) * 100

      - percent_left <= 20%          -> HIGH risk
      - 20% < percent_left <= 40%    -> MEDIUM risk
      - 40% < percent_left <= 50%    -> LOW risk
      - percent_left >= 51%          -> not considered vulnerable

    For every vulnerable user we:
      - store a doc in financially_vulnerable_users collection
      - update any advisor-client links (clients_col) to set priority to
        high/medium/low if the client has accepted the advisor.
    """
    if session.get("role") != "Compliance Regulator":
        return jsonify({"ok": False, "message": "Unauthorized"}), 403

    data = request.get_json(silent=True) or {}
    # Window in days to look back at transactions (default 30 days)
    try:
        days = int(data.get("days", 30))
    except (TypeError, ValueError):
        days = 30

    cutoff_date = datetime.utcnow().date() - timedelta(days=days)

    # Clear previous snapshot so this collection always reflects
    # the latest vulnerability assessment.
    financially_vulnerable_col.delete_many({})

    vulnerable_results = []
    scanned_accounts = 0

    # Iterate all Plaid-connected accounts
    for acct in bank_accounts_col.find({}):
        user_id_str = acct.get("user_id")
        if not user_id_str:
            continue

        try:
            user_obj_id = ObjectId(user_id_str)
        except Exception:
            continue

        user_doc = users_col.find_one({"_id": user_obj_id})
        if not user_doc:
            continue

        txs = acct.get("recent_transactions", [])
        if not txs:
            continue

        scanned_accounts += 1

        # Reuse your existing Plaid summary builder to get income/expenses
        summary = _build_plaid_summary(txs, cutoff_date)
        total_income = float(sum(summary.get("income", [])))
        total_expenses = float(sum(summary.get("expenses", [])))  # already positive

        # If we truly have no income and no expenses in this window, skip
        if total_income <= 0 and total_expenses <= 0:
            continue

        # net = income - expenses
        net = total_income - total_expenses

        # Percent of income left. If no income but expenses exist,
        # treat as 0% left (worst case).
        if total_income <= 0:
            percent_left = 0.0
        else:
            percent_left = (net / total_income) * 100.0

        # Determine risk level
        risk_level = None
        if percent_left <= 20:
            risk_level = "high"
        elif percent_left <= 40:
            risk_level = "medium"
        elif percent_left <= 50:
            risk_level = "low"
        else:
            # 51% or more left -> not financially vulnerable
            continue

        # Build stored document
        doc = {
            "user_id": user_id_str,
            "username": user_doc.get("username"),
            "email": user_doc.get("email"),
            "fullName": user_doc.get("fullName"),
            "percent_income_left": round(percent_left, 2),
            "total_income": round(total_income, 2),
            "total_expenses": round(total_expenses, 2),
            "net_amount": round(net, 2),
            "current_balance": float(acct.get("current_balance") or 0.0),
            "risk_level": risk_level,
            "computed_at": datetime.utcnow(),
        }

        # Upsert into financially_vulnerable_users so we have a
        # persistent snapshot collection regulators/advisors can query.
        financially_vulnerable_col.update_one(
            {"user_id": user_id_str},
            {"$set": doc},
            upsert=True,
        )

        # Update advisor priority for any accepted advisor-client links
        clients_col.update_many(
            {"user_id": user_obj_id, "status": "Accepted"},
            {"$set": {"priority": risk_level}}
        )

        vulnerable_results.append(doc)

    return jsonify({
        "ok": True,
        "window_days": days,
        "scanned_accounts": scanned_accounts,
        "vulnerable_count": len(vulnerable_results),
        "vulnerable_users": vulnerable_results,
    })

@app.route("/api/compliance/financially_vulnerable", methods=["GET"])
@login_required
def api_get_financially_vulnerable():
    """
    Return the most recently stored snapshot of financially vulnerable users.
    Does NOT re-run the scan; call /api/compliance/financially_vulnerable/scan
    to recompute and refresh.
    """
    if session.get("role") != "Compliance Regulator":
        return jsonify({"ok": False, "message": "Unauthorized"}), 403

    risk_filter = (request.args.get("risk") or "").lower()
    query = {}
    if risk_filter in ("high", "medium", "low"):
        query["risk_level"] = risk_filter

    docs = list(financially_vulnerable_col.find(query).sort("percent_income_left", 1))

    result = []
    for d in docs:
        result.append({
            "user_id": d.get("user_id"),
            "username": d.get("username"),
            "email": d.get("email"),
            "fullName": d.get("fullName"),
            "percent_income_left": d.get("percent_income_left"),
            "total_income": d.get("total_income"),
            "total_expenses": d.get("total_expenses"),
            "net_amount": d.get("net_amount"),
            "current_balance": d.get("current_balance"),
            "risk_level": d.get("risk_level"),
            "computed_at": d.get("computed_at").isoformat() if d.get("computed_at") else None,
        })

    return jsonify({"ok": True, "vulnerable_users": result})

@app.route("/api/user/financial_status")
@login_required
def api_user_financial_status():
    """
    Return whether the currently logged-in *regular user* is considered
    financially vulnerable, based on the latest scan results stored in
    financially_vulnerable_users.

    If there is no record, we treat the user as *not* vulnerable.
    """
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"ok": False, "message": "Not logged in"}), 401

    doc = financially_vulnerable_col.find_one({"user_id": user_id})
    if not doc:
        return jsonify({
            "ok": True,
            "vulnerable": False
        })

    return jsonify({
        "ok": True,
        "vulnerable": True,
        "risk_level": doc.get("risk_level"),
        "percent_income_left": doc.get("percent_income_left"),
        "current_balance": doc.get("current_balance"),
        "total_income": doc.get("total_income"),
        "total_expenses": doc.get("total_expenses"),
        "net_amount": doc.get("net_amount"),
        "computed_at": doc.get("computed_at").isoformat() if doc.get("computed_at") else None,
    })


@app.route("/api/compliance/get_settings")
@login_required
def api_compliance_get_settings():
    if session.get("role") != "Compliance Regulator":
        return jsonify({"ok": False, "message": "Unauthorized"}), 403

    doc = compliance_settings_col.find_one({"_id": "global"}) or {}

    return jsonify({
        "ok": True,
        "settings": {
            "enable_data_masking": doc.get("enable_data_masking", True),
            "enable_ip_logging": doc.get("enable_ip_logging", False),
            "auto_anonymize": doc.get("auto_anonymize", True),
            "notify_critical": doc.get("notify_critical", True),
            "track_admin": doc.get("track_admin", True),
            "retention_days": doc.get("retention_days", 90),
        }
    })



@app.route("/")
def login_page():
    return render_template("login.html")


@app.route("/register.html")
def register_page():
    return render_template("register.html")


@app.route("/dashboard.html")
@login_required
def dashboard():
    user = get_current_user()
    # Redirect ONLY if simp_dash is true
    if user and user.get("simp_dash"):
        return redirect("/simplified-dashboard.html")

    return render_template("dashboard.html", active_page="dashboard")

@app.route("/simplified-dashboard.html")
@login_required
def simplified_dashboard():
    return render_template("simplified_dashboard.html", active_page="dashboard")


@app.route("/transaction-list.html")
@login_required
def transaction_list_page():
    return render_template("transaction-list.html", active_page="alerts")


@app.route("/compliance-dashboard.html")
@login_required
def compliance_dashboard():
    if session.get("role") != "Compliance Regulator":
        return redirect("/dashboard.html")
    return render_template("compliance-dashboard.html")  # separate shell


@app.route("/settings.html")
@login_required
def settings_page():
    return render_template("settings.html", active_page="settings")


@app.route("/transaction-details.html")
@login_required
def transaction_details_page():
    return render_template("transaction-details.html", active_page="transactions")


@app.route("/edit-profile.html")
@login_required
def edit_profile_page():
    return render_template("edit_profile.html", active_page="settings")


@app.route("/ai-insights")
@login_required
def ai_insights_page():
    return render_template("ai_insights.html", active_page="ai_insights")


@app.route("/compliance/transactions")
@login_required
def transactions_page():
    return render_template("transaction-table.html")  # compliance-specific


@app.route("/compliance-settings.html")
@login_required
def compliance_settings_page():
    if session.get("role") != "Compliance Regulator":
        return redirect("/dashboard.html")
    return render_template("compliance-settings.html")


@app.route("/budget-limit")
@login_required
def budget_limit_page():
    return render_template("budget_limit.html", active_page="budget_limit")


@app.route("/entry")
@login_required
def entry_page():
    return render_template("entry.html", active_page="entry")


@app.route("/flagged_users.html")
@login_required
def flagged_users_page():
    if session.get("role") != "Compliance Regulator":
        return redirect("/dashboard.html")
    return render_template("flagged_users.html")



@app.route("/compliance/user/<user_id>")
@login_required
def compliance_user_page(user_id):
    if session.get("role") != "Compliance Regulator":
        return redirect("/dashboard.html")

    user = users_col.find_one({"_id": ObjectId(user_id)})
    if not user:
        return "User not found", 404

    return render_template("compliance_user.html", user=user)

@app.route("/api/user/advisors")
@login_required
def api_user_advisors():
    """
    Return all Financial Advisor accounts for the dropdown on the
    regular user's settings page.
    """
    # Only regular users really need this, but it's harmless for others.
    # You can restrict if you want:
    # if session.get("role") != "Average User":
    #     return jsonify({"ok": False, "message": "Unauthorized"}), 403

    advisors = list(users_col.find({
        "role": "Financial Advisor"   # role stored via normalize_role
    }))

    items = []
    for a in advisors:
        items.append({
            "id": str(a["_id"]),
            "name": a.get("fullName") or a.get("username") or "Advisor",
            "email": a.get("email", "")
        })

    return jsonify({"ok": True, "advisors": items})

@app.route("/api/user/select_advisor", methods=["POST"])
@login_required
def api_user_select_advisor():
    """
    Regular user selects an advisor from the dropdown.

    Creates a clients_col row with:
      - user_id = current user
      - advisor_id = chosen advisor
      - status = 'Accepted' (user is explicitly consenting)
      - priority = derived from vulnerability risk (high/medium/low)
    """
    if session.get("role") != "Average User":
        return jsonify({"ok": False, "message": "Only regular users can add an advisor"}), 403

    data = request.get_json(silent=True) or {}
    advisor_id_str = data.get("advisor_id")

    if not advisor_id_str:
        return jsonify({"ok": False, "message": "advisor_id is required"}), 400

    user_id_str = session.get("user_id")
    try:
        user_obj_id = ObjectId(user_id_str)
        advisor_obj_id = ObjectId(advisor_id_str)
    except Exception:
        return jsonify({"ok": False, "message": "Invalid id"}), 400

    # Check advisor exists & is actually an advisor
    advisor_doc = users_col.find_one({"_id": advisor_obj_id})
    if not advisor_doc:
        return jsonify({"ok": False, "message": "Advisor not found"}), 404

    if normalize_role(advisor_doc.get("role")) != "Financial Advisor":
        return jsonify({"ok": False, "message": "Selected user is not a Financial Advisor"}), 400

    # Prevent duplicate advisor-client links
    existing = clients_col.find_one({
        "advisor_id": advisor_obj_id,
        "user_id": user_obj_id
    })
    if existing:
        return jsonify({
            "ok": False,
            "message": "You are already a client of this advisor."
        }), 409

    # Try to pull latest vulnerability snapshot for priority:
    vuln_doc = financially_vulnerable_col.find_one({"user_id": user_id_str})
    risk_level = (vuln_doc or {}).get("risk_level", "low")  # "high" / "medium" / "low"

    now = datetime.utcnow()

    clients_col.insert_one({
        "user_id": user_obj_id,
        "advisor_id": advisor_obj_id,
        "priority": risk_level,
        "status": "Accepted",
        "notes": "",
        "created_at": now,
        "permission_requested_at": now,
        "permission_updated_at": now,
        "budget_edit_status": "none",
    })

    # Optional: notify the advisor that a new client has been added
    user_doc = users_col.find_one({"_id": user_obj_id})
    user_name = user_doc.get("fullName", "A user") if user_doc else "A user"

    notifications_col.insert_one({
        "user_id": advisor_obj_id,
        "message": f"{user_name} has added you as their advisor.",
        "type": "new_client",
        "created_at": datetime.utcnow(),
        "read": False,
    })

    return jsonify({
        "ok": True,
        "message": "Advisor added successfully. They will now see you in their client list.",
        "priority": risk_level,
    })


# ============================================
# API — FLAGGED USERS (aggregated by user)
# ============================================
@app.route("/api/compliance/flagged_users")
@login_required
def api_flagged_users():
    if session.get("role") != "Compliance Regulator":
        return jsonify({"ok": False, "message": "Unauthorized"}), 403

    pipeline = [
        {
            "$group": {
                "_id": "$transaction.user_id",
                "flagCount": {"$sum": 1},
                "lastActivity": {"$max": "$created_at"},
                "risks": {"$push": "$risk"}
            }
        }
    ]

    raw = list(flagged_col.aggregate(pipeline))
    output = []

    for u in raw:
        user_doc = users_col.find_one({"_id": ObjectId(u["_id"])}) if u["_id"] else None

        # Determine highest-risk level
        risks = u.get("risks", [])
        if "Critical" in risks:
            risk = "Critical"
        elif "High" in risks:
            risk = "High"
        elif "Medium" in risks:
            risk = "Medium"
        else:
            risk = "Low"

        output.append({
            "user_id": str(u["_id"]),
            "name": user_doc.get("fullName") if user_doc else "Unknown",
            "email": user_doc.get("email") if user_doc else "Unknown",
            "flagged_transactions": u["flagCount"],
            "risk": risk,
            "last_activity": u["lastActivity"].isoformat() if u["lastActivity"] else None
        })

    return jsonify({"ok": True, "users": output})


@app.route("/advisor_dashboard")
@login_required
def advisor_dashboard_page():
    if session.get("role") != "Financial Advisor":
        return redirect("/dashboard.html")
    return render_template("advisor_dashboard.html")

@app.route("/transaction-table.html")
@login_required
def transaction_table_page():
    return render_template("transaction-table.html")



@app.route("/advisor_clients")
@login_required
def advisor_clients_page():
    if session.get("role") != "Financial Advisor":
        return redirect("/dashboard.html")
    return render_template("advisor_clients.html")

@app.route("/advisor-settings")
def advisor_settings():
    return render_template("advisor-settings.html")

# =========================================
# AI CHAT API ENDPOINT
# =========================================

def build_budget_prompt(user_id: str, user_message: str, max_transactions: int = 25) -> str:
    """
    Build a big text prompt for the LLM using the user's net income,
    total income, total expenses and recent transactions.

    Prefers Plaid data; falls back to manual entries if no bank connection.
    """
    # Get a display name
    user_doc = users_col.find_one({"_id": ObjectId(user_id)})
    display_name = (
        (user_doc or {}).get("fullName")
        or (user_doc or {}).get("username")
        or "the user"
    )

    # Try Plaid first
    bank_doc = bank_accounts_col.find_one({"user_id": user_id})
    tx_lines: list[str] = []
    total_income = 0.0
    total_expenses = 0.0

    if bank_doc and bank_doc.get("recent_transactions"):
        txs = bank_doc["recent_transactions"]

        # Compute totals
        for tx in txs:
            amount = float(tx.get("amount") or 0)
            name = tx.get("name", "")
            cat = tx.get("category", "Other")
            is_income = _classify_direction(name, cat)

            signed = amount if is_income else -amount
            if signed >= 0:
                total_income += signed
            else:
                total_expenses += abs(signed)

        # Most recent first, limit to max_transactions
        txs_sorted = sorted(txs, key=lambda x: x.get("date", ""), reverse=True)[:max_transactions]
        for tx in txs_sorted:
            tx_lines.append(
                f"{tx.get('date')} | {tx.get('name')} | {tx.get('category')} | {tx.get('amount')}"
            )
    else:
        # Fallback: manual entries collection
        entries = list(entries_col.find({"user_id": user_id}).sort("created_at", -1))
        for e in entries:
            amount = float(e.get("amount", 0) or 0)
            typ = str(e.get("type", "")).lower()
            cat = e.get("category", "Other")

            if typ == "income":
                total_income += amount
            elif typ == "expense":
                total_expenses += amount

            tx_lines.append(
                f"{e.get('created_at')} | {typ} | {cat} | {amount}"
            )

        tx_lines = tx_lines[:max_transactions]

    net_income = total_income - total_expenses

    tx_block = (
        "\n".join(f"- {line}" for line in tx_lines)
        if tx_lines
        else "No transactions available in this period."
    )

    # Your requested style of prompt:
    prompt = f"""Be a friendly ai chat bot assistant and if requested to improve budget or finances or questions about either Based on {display_name}'s net income: {net_income:.2f},
total expenses: {total_expenses:.2f}, total income: {total_income:.2f},
and the following recent transactions (up to {max_transactions}):

{tx_block}

Formulate a budget plan the user could use to better improve their finances in a general sense.
Be specific, including details they should avoid or reduce. For example:
"spend less on eating out to save better, as the transaction 'Uber Eats' was seen 4 times this month,
which when reduced could lead to better finances."

Requirements:
- Focus ONLY on budgeting and spending habits (no investing, tax or legal advice).
- Call out any categories or merchants that look high.
- Give 5–10 concrete, numbered action steps.
- Keep the tone supportive and non-judgmental.
- Keep the answer under 400 words.

The user also said: "{user_message}".
"""
    return prompt

@app.route("/api/ai-chat", methods=["POST"])
@login_required
def api_ai_chat():
    data = request.get_json(silent=True) or {}
    msg = (data.get("message") or "").strip()

    if not msg:
        return jsonify({"reply": "Please type something to chat!"})

    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"reply": "You must be logged in to use AI chat."}), 401

    # Build a rich prompt from DB + the user message
    budget_prompt = build_budget_prompt(user_id, msg)

    try:
        response = hf_client.chat_completion(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are BudgetMind AI, a friendly but serious personal-finance coach. "
                        "You ONLY give safe budgeting and spending advice based on the data provided. "
                        "Do not give investing, tax, or legal advice."
                        "You Have a bright personality but a realistic one."
                        "You can talk to the users like a normal person."
                    ),
                },
                {
                    "role": "user",
                    "content": budget_prompt,
                },
            ],
            max_tokens=800,
            temperature=0.7,
        )

        # huggingface_hub ChatCompletionOutput
        reply = response.choices[0].message.content

    except Exception as e:
        print("AI Chat error:", e)
        reply = "⚠️ I couldn't reach the AI service right now."

    return jsonify({"reply": reply})

# =========================================
# AI INSIGHTS HELPERS
# =========================================

def build_ai_budget_context(user_id: str, lookback_days: int = 30, max_transactions: int = 25) -> dict:
    """
    Build numeric summary + a text list of recent transactions for the user.

    Returns a dict with:
      - display_name
      - total_income
      - total_expenses
      - net_income
      - transactions_text
    """
    # Friendly name for prompt
    user_doc = users_col.find_one({"_id": ObjectId(user_id)})
    display_name = (
        (user_doc or {}).get("fullName")
        or (user_doc or {}).get("username")
        or "the user"
    )

    bank_doc = bank_accounts_col.find_one({"user_id": user_id})
    total_income = 0.0
    total_expenses = 0.0
    tx_lines = []

    # Prefer Plaid-connected data
    if bank_doc and bank_doc.get("recent_transactions"):
        cutoff = datetime.utcnow().date() - timedelta(days=lookback_days)

        # Reuse your plaid summary builder
        try:
            summary = _build_plaid_summary(bank_doc["recent_transactions"], cutoff)
        except Exception:
            summary = {"income": [], "expenses": [], "transactions": []}

        total_income = float(sum(summary.get("income", [])))
        total_expenses = float(sum(summary.get("expenses", [])))

        # Take up to N most recent tx from summary
        tx_list = summary.get("transactions", [])[:max_transactions]
        for tx in tx_list:
            tx_lines.append(
                f"{tx.get('date')} | {tx.get('name')} | {tx.get('category')} | {tx.get('amount')}"
            )
    else:
        # Fallback: manual entries if no bank connection
        cutoff_dt = datetime.utcnow() - timedelta(days=lookback_days)
        entries = entries_col.find({
            "user_id": user_id,
            "created_at": {"$gte": cutoff_dt},
        }).sort("created_at", -1)

        for e in entries:
            try:
                amt = float(e.get("amount") or 0)
            except (TypeError, ValueError):
                continue

            typ = str(e.get("type", "")).lower()
            cat = e.get("category", "Other")
            created_at = e.get("created_at")
            if isinstance(created_at, datetime):
                dstr = created_at.date().isoformat()
            else:
                dstr = str(created_at)

            if typ == "income":
                total_income += amt
            elif typ == "expense":
                total_expenses += amt

            tx_lines.append(f"{dstr} | {typ} | {cat} | {amt}")
            if len(tx_lines) >= max_transactions:
                break

    net_income = total_income - total_expenses

    transactions_text = (
        "\n".join(f"- {line}" for line in tx_lines)
        if tx_lines
        else "No recent transactions available in this period."
    )

    return {
        "display_name": display_name,
        "total_income": round(total_income, 2),
        "total_expenses": round(total_expenses, 2),
        "net_income": round(net_income, 2),
        "transactions_text": transactions_text,
    }


def build_insights_prompt(user_id: str, max_transactions: int = 25) -> str:
    """
    Build the natural-language prompt for AI insights using the user's income,
    expenses, net income, and recent transactions.
    """
    ctx = build_ai_budget_context(
        user_id=user_id,
        lookback_days=30,
        max_transactions=max_transactions,
    )

    display_name = ctx["display_name"]
    total_income = ctx["total_income"]
    total_expenses = ctx["total_expenses"]
    net_income = ctx["net_income"]
    tx_text = ctx["transactions_text"]

    prompt = f"""
Based on {display_name}'s recent finances:

- Net income (income - expenses): {net_income:.2f}
- Total income: {total_income:.2f}
- Total expenses: {total_expenses:.2f}

Recent transactions (most recent first, up to {max_transactions}):

{tx_text}

Using ONLY this information:

Formulate a practical budget plan that could help {display_name} improve their finances in a general sense.

Be specific, including details about categories or merchants they might reduce.
For example: "🍔 Spend less on eating out, as 'Uber Eats' appears multiple times; skipping one order per week would free extra money for savings."

Output rules:
- Return EXACTLY 3 bullet points.
- Each bullet must start with an emoji.
- Each bullet should be a single clear sentence.
- Focus only on budgeting and spending habits (do NOT give investing, tax, or legal advice).
"""
    return prompt.strip()


def extract_insights(text: str, max_items: int = 3) -> list:
    """
    Convert the raw LLM reply into up to 3 clean bullet lines.
    """
    lines = [ln.strip(" -•\t") for ln in text.splitlines() if ln.strip()]
    out = []
    for ln in lines:
        if ln:
            out.append(ln)
        if len(out) >= max_items:
            break
    return out

# =========================================
# AI INSIGHTS API ENDPOINT
# =========================================

@app.route("/api/ai-insights", methods=["POST"])
@login_required
def api_ai_insights():
    """
    Return 3 short AI-generated budgeting insights for the logged-in user.

    Response:
      { "ok": true/false, "insights": [ "...", "...", "..." ] }
    """
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"ok": False, "message": "Not logged in"}), 401

    # If somehow the client isn't set, give a safe fallback
    if hf_client is None:
        fallback = [
            "💡 Set a simple weekly spending limit and review it every Sunday.",
            "🧾 Review your subscriptions each month and cancel ones you rarely use.",
            "💰 Move a fixed amount into savings right after each payday.",
        ]
        return jsonify({"ok": True, "source": "fallback", "insights": fallback})

    prompt = build_insights_prompt(user_id, max_transactions=25)

    try:
        response = hf_client.chat_completion(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a concise budgeting coach. "
                        "You ONLY talk about budgeting, saving and spending habits. "
                        "You DO NOT give investing, tax, or legal advice. "
                        "You must return exactly 3 short bullet-style tips."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            max_tokens=512,
            temperature=0.6,
        )

        raw = response.choices[0].message.content or ""
        raw = raw.strip()
        insights = extract_insights(raw, max_items=3)

        if not insights:
            insights = [
                "💡 Track one category this month (like dining out) and aim to cut it by 10%.",
                "📊 Set a simple monthly budget for essentials, wants, and savings.",
                "🏦 Pay more than the minimum on any card to reduce interest over time.",
            ]

        return jsonify({"ok": True, "insights": insights})

    except Exception as e:
        print("AI Insights error:", e)
        fallback = [
            "⚠️ AI is currently unavailable.",
            "🧾 Review your top spending categories manually this week.",
            "💰 Choose one recurring expense you can reduce or cancel.",
        ]
        return jsonify({"ok": False, "insights": fallback, "message": "AI service unavailable"}), 500

@app.route("/api/advisor/clients")
@login_required
def api_advisor_clients():
    if session.get("role") != "Financial Advisor":
        return jsonify({"ok": False, "message": "Unauthorized"}), 403

    advisor_id_str = session.get("user_id")
    try:
        advisor_obj_id = ObjectId(advisor_id_str)
    except Exception:
        return jsonify({"ok": False, "message": "Invalid advisor id"}), 400

    # 🔥 Only return accepted clients
    links = list(clients_col.find({
        "advisor_id": advisor_obj_id,
        "status": "Accepted"
    }))

    output = []
    for link in links:
        user_doc = users_col.find_one({"_id": link.get("user_id")})
        if not user_doc:
            continue

        output.append({
            "_id": str(link["_id"]),
            "user_id": str(user_doc["_id"]),
            "full_name": user_doc.get("fullName", "Unknown"),
            "email": user_doc.get("email", ""),
            "priority": link.get("priority", "low"),
            "status": link.get("status", "Accepted"),
            "created_at": (
                link.get("created_at").isoformat()
                if link.get("created_at") else None
            ),
        })

    return jsonify(output)


from fpdf import FPDF  # make sure to pip install fpdf

@app.route("/api/compliance/export_csv")
@login_required
def api_export_csv():
    import csv
    from io import StringIO

    # Only regulators or advisors
    if session.get("role") not in ["Compliance Regulator", "Financial Advisor"]:
        return jsonify({"ok": False, "message": "Unauthorized"}), 403

    # Pull all flagged activities from DB
    flagged = list(flagged_col.find({}))  # OR wherever your flags are stored

    # Create CSV buffer
    csv_buffer = StringIO()

    # If NO data → return empty CSV with a placeholder header
    if not flagged:
        writer = csv.writer(csv_buffer)
        writer.writerow(["message"])
        writer.writerow(["No flagged activities available"])
    else:
        # Use keys from first document
        fieldnames = list(flagged[0].keys())

        writer = csv.DictWriter(csv_buffer, fieldnames=fieldnames)
        writer.writeheader()

        for item in flagged:
            writer.writerow(item)

    csv_buffer.seek(0)

    return Response(
        csv_buffer.getvalue(),
        mimetype="text/csv",
        headers={
            "Content-Disposition": "attachment; filename=flagged_activities.csv"
        }
    )

def compute_simplified_flows(user_id: str, max_items: int = 50):
    """
    Return totals + separate lists of income and expenses for the user.

    Prefers Plaid (bank_accounts_col.recent_transactions), falls back to manual entries.
    Each list is capped at max_items, ordered from most recent to oldest.
    """
    income_streams = []
    expense_streams = []
    total_income = 0.0
    total_expense = 0.0

    # -------- PLAID FIRST --------
    bank_doc = bank_accounts_col.find_one({"user_id": user_id})
    if bank_doc and bank_doc.get("recent_transactions"):
        txs = bank_doc["recent_transactions"]

        # Sort newest first
        txs_sorted = sorted(txs, key=lambda x: x.get("date", ""), reverse=True)

        for tx in txs_sorted:
            amount = float(tx.get("amount") or 0)
            name = tx.get("name", "")
            cat = tx.get("category", "Other")
            is_income = _classify_direction(name, cat)

            item = {
                "date": tx.get("date"),
                "name": name,
                "category": cat,
                "amount": amount,
                "transaction_id": tx.get("transaction_id"),
            }

            if is_income:
                total_income += amount
                if len(income_streams) < max_items:
                    income_streams.append(item)
            else:
                total_expense += amount  # keep expenses as positive for reporting
                if len(expense_streams) < max_items:
                    expense_streams.append(item)

        return {
            "source": "plaid",
            "total_income": round(total_income, 2),
            "total_expense": round(total_expense, 2),
            "income_streams": income_streams,
            "expense_streams": expense_streams,
        }

    # -------- FALLBACK: MANUAL ENTRIES --------
    entries = list(
        entries_col.find({"user_id": user_id}).sort("created_at", -1)
    )

    for e in entries:
        amount = float(e.get("amount", 0) or 0)
        typ = str(e.get("type", "")).lower()
        cat = e.get("category", "Other")
        created_at = e.get("created_at")

        item = {
            "date": created_at.isoformat() if isinstance(created_at, datetime) else str(created_at),
            "name": cat,
            "category": cat,
            "amount": amount,
            "transaction_id": None,
        }

        if typ == "income":
            total_income += amount
            if len(income_streams) < max_items:
                income_streams.append(item)
        elif typ == "expense":
            total_expense += amount
            if len(expense_streams) < max_items:
                expense_streams.append(item)

    return {
        "source": "manual",
        "total_income": round(total_income, 2),
        "total_expense": round(total_expense, 2),
        "income_streams": income_streams,
        "expense_streams": expense_streams,
    }

@app.route("/api/simplified/flows")
@login_required
def api_simplified_flows():
    """
    Returns totals + lists of income and expense streams (up to 50 each).
    This is what simplified_dashboard.js will call to render the two lists.
    """
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"ok": False, "message": "Not logged in"}), 401

    flows = compute_simplified_flows(user_id, max_items=50)

    return jsonify({
        "ok": True,
        "source": flows["source"],
        "total_income": flows["total_income"],
        "total_expense": flows["total_expense"],
        "income_streams": flows["income_streams"],
        "expense_streams": flows["expense_streams"],
    })

@app.route("/api/simplified/summary")
@login_required
def api_simplified_summary():
    """
    Uses income/expenses to compute:
      - net_income
      - savings_target = 20% of net_income (never less than 0)
    Front-end can later use this to show how far up/down the user is vs that 20% target.
    """
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"ok": False, "message": "Not logged in"}), 401

    flows = compute_simplified_flows(user_id, max_items=50)

    total_income = flows["total_income"]
    total_expense = flows["total_expense"]
    net_income = total_income - total_expense

    # savings is defined as 20% of net income; if net is negative, treat savings as 0
    savings_target = max(net_income * 0.20, 0.0)

    return jsonify({
        "ok": True,
        "source": flows["source"],
        "total_income": total_income,
        "total_expense": total_expense,
        "net_income": round(net_income, 2),
        "savings_target": round(savings_target, 2),
        # helpful extra fields for your simplified_dashboard later
        "income_streams_count": len(flows["income_streams"]),
        "expense_streams_count": len(flows["expense_streams"]),
    })


from fpdf import FPDF
import os
from flask import send_file
from io import BytesIO

@app.route("/api/compliance/export_pdf")
@login_required
def api_export_pdf():
    from io import BytesIO
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
    from reportlab.lib import colors
    from reportlab.lib.units import inch

    # Role check
    if session.get("role") not in ["Compliance Regulator", "Financial Advisor"]:
        return jsonify({"ok": False, "message": "Unauthorized"}), 403

    # Fetch all accounts
    all_docs = list(bank_accounts_col.find({}))

    # PDF buffer
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    styles = getSampleStyleSheet()
    flow = []

    # Title
    flow.append(Paragraph("<b>BudgetMind AI — System Transaction Report</b>", styles["Title"]))
    flow.append(Spacer(1, 0.2 * inch))

    # Loop accounts
    for acct in all_docs:
        user_id = acct.get("user_id")
        user_doc = None

        if user_id:
            try:
                user_doc = users_col.find_one({"_id": ObjectId(user_id)})
            except:
                user_doc = None

        email = user_doc["email"] if user_doc else "Unknown"

        # User header
        flow.append(Paragraph(f"<b>User:</b> {email}", styles["Heading3"]))
        flow.append(Paragraph(f"<b>Balance:</b> ${acct.get('current_balance', 0):,.2f}", styles["Normal"]))
        flow.append(Spacer(1, 0.15 * inch))

        txs = acct.get("recent_transactions", [])

        if not txs:
            flow.append(Paragraph("<i>No transactions available.</i>", styles["Italic"]))
            flow.append(Spacer(1, 0.2 * inch))
            continue

        # Transactions
        for tx in txs:
            date = tx.get("date", "")
            name = tx.get("name", "")
            cat = tx.get("category", "")
            amt = tx.get("amount", 0)

            # ALL ASCII OR UNICODE SAFE — reportlab never crashes
            line = f"{date} — {name} — {cat} — ${amt:,.2f}"

            flow.append(Paragraph(line, styles["Normal"]))
        
        flow.append(Spacer(1, 0.3 * inch))

    doc.build(flow)
    buffer.seek(0)

    return send_file(
        buffer,
        mimetype="application/pdf",
        as_attachment=True,
        download_name="transaction_report.pdf"
    )







@app.route("/advisor_priority")
@login_required
def advisor_priority_page():
    if session.get("role") != "Financial Advisor":
        return redirect("/dashboard.html")
    return render_template("advisor_priority.html")


@app.route("/advisor_summary")
@login_required
def advisor_summary_page():
    if session.get("role") != "Financial Advisor":
        return redirect("/dashboard.html")
    return render_template("advisor_summary.html")


@app.route("/api/advisor/check_overspending", methods=["POST"])
@login_required
def api_check_overspending():
    if session.get("role") != "Financial Advisor":
        return jsonify({"ok": False, "message": "Unauthorized"}), 403

    data = request.get_json() or {}
    client_link_id = data.get("client_id")
    time_filter = data.get("time_filter", "month")

    if not client_link_id:
        return jsonify({"ok": False, "message": "Missing client id"}), 400

    # Make sure this advisor *owns* the link AND the client has granted permission
    link, error = _get_advisor_client_link(client_link_id, require_accepted=True)
    if error:
        return error

    client_user_id = str(link["user_id"])
    advisor_id = ObjectId(session["user_id"])

    # Time filter
    now = datetime.utcnow().date()
    if time_filter == "month":
        cutoff = now - timedelta(days=30)
    elif time_filter == "quarter":
        cutoff = now - timedelta(days=90)
    else:
        cutoff = now - timedelta(days=365)

    # Fetch Plaid data
    bank_doc = bank_accounts_col.find_one({"user_id": client_user_id})
    if not bank_doc:
        return jsonify({"ok": True, "overspending": False, "reason": "No bank data"})

    txs = bank_doc.get("recent_transactions", [])
    total_spent = 0.0

    for tx in txs:
        d_str = tx.get("date")
        try:
            d = datetime.fromisoformat(d_str).date()
            if d < cutoff:
                continue
        except Exception:
            continue

        amt = float(tx.get("amount", 0))
        name = tx.get("name", "")
        cat = tx.get("category", "")

        is_income = _classify_direction(name, cat)
        if not is_income:
            total_spent += abs(amt)

    # Spending limit (default = 1000)
    user_doc = users_col.find_one({"_id": link["user_id"]})
    spending_limit = float(user_doc.get("spending_limit", DEFAULT_SPENDING_LIMIT))

    overspending = total_spent > spending_limit

    # Store alert if overspending
    if overspending:
        db.alerts.insert_one({
            "client_id": client_user_id,
            "advisor_id": advisor_id,
            "timestamp": datetime.utcnow(),
            "amount_spent": total_spent,
            "budget_limit": spending_limit,
            "type": "overspending"
        })

    return jsonify({
        "ok": True,
        "overspending": overspending,
        "total_spent": round(total_spent, 2),
        "budget_limit": spending_limit
    })




@app.route("/api/advisor/alert_summary/<client_link_id>")
@login_required
def api_alert_summary(client_link_id):
    if session.get("role") != "Financial Advisor":
        return jsonify({"ok": False, "message": "Unauthorized"}), 403

    # Ensure advisor owns this client AND permission is granted
    link, error = _get_advisor_client_link(client_link_id, require_accepted=True)
    if error:
        return error

    client_user_obj_id = link["user_id"]
    client_user_id = str(client_user_obj_id)

    # 🔹 get the *current* budget limit from the user record
    user_doc = users_col.find_one({"_id": client_user_obj_id}) or {}
    try:
        current_limit = float(user_doc.get("spending_limit", DEFAULT_SPENDING_LIMIT))
    except (TypeError, ValueError):
        current_limit = DEFAULT_SPENDING_LIMIT

    alerts = list(
        db.alerts.find({"client_id": client_user_id}).sort("timestamp", -1)
    )

    formatted = []
    for a in alerts:
        formatted.append({
            "timestamp": a["timestamp"].isoformat(),
            "type": a.get("type", "overspending"),
            "spent": a.get("amount_spent", 0),
            # 🔹 always show the latest limit instead of the historical one
            "limit": current_limit,
        })

    return jsonify({"ok": True, "alerts": formatted})



@app.route("/api/advisor/budget_edit_status/<client_link_id>")
@login_required
def api_budget_edit_status(client_link_id):
    """
    Advisor checks whether they can edit a client’s budget limit.
    Status:
      - 'no_client_permission'  -> client hasn’t accepted advisor at all
      - 'none'                  -> client accepted advisor, but no budget-edit request yet
      - 'pending'               -> request sent, waiting on client
      - 'granted'               -> client allowed budget edits
      - 'denied'                -> client explicitly denied
    """
    if session.get("role") != "Financial Advisor":
        return jsonify({"ok": False, "message": "Unauthorized"}), 403

    link, error = _get_advisor_client_link(client_link_id, require_accepted=False)
    if error:
        return error

    if link.get("status") != "Accepted":
        status = "no_client_permission"
    else:
        status = link.get("budget_edit_status", "none")

    return jsonify({"ok": True, "status": status})


@app.route("/api/advisor/budget_edit_request", methods=["POST"])
@login_required
def api_budget_edit_request():
    """
    Advisor clicks 'Request Access' – ask client for permission to edit budget limit.
    """
    if session.get("role") != "Financial Advisor":
        return jsonify({"ok": False, "message": "Unauthorized"}), 403

    data = request.get_json(silent=True) or {}
    client_id = data.get("client_id")
    if not client_id:
        return jsonify({"ok": False, "message": "client_id required"}), 400

    # Must own this link AND client must have accepted being a client
    link, error = _get_advisor_client_link(client_id, require_accepted=True)
    if error:
        return error

    clients_col.update_one(
        {"_id": link["_id"]},
        {"$set": {
            "budget_edit_status": "pending",
            "budget_edit_requested_at": datetime.utcnow(),
            "budget_edit_updated_at": None,
        }},
    )

    return jsonify({"ok": True, "status": "pending"})



@app.route("/api/advisor/save_client_settings", methods=["POST"])
@login_required
def api_save_client_settings():
    data = request.get_json()
    client_id = data.get("client_id")

    if not client_id:
        return jsonify(ok=False, message="Missing client_id"), 400

    payload = {
        "total_budget": data.get("total_budget", 0),
        "categories": {
            "groceries": data.get("categories", {}).get("groceries", 0),
            "dining": data.get("categories", {}).get("dining", 0),
            "transport": data.get("categories", {}).get("transport", 0),
            "bills": data.get("categories", {}).get("bills", 0),
        },
        "dashboard": data.get("dashboard", {}),
        "notes": data.get("notes", "")
    }

    # Save settings to DB
    db.client_settings.update_one(
        {"client_id": client_id},
        {"$set": payload},
        upsert=True
    )

    # -----------------------------------
    # ADVISOR NOTES COLLECTION INSERTION
    # -----------------------------------
    if data.get("notes"):
        # Fetch advisor info
        advisor = users_col.find_one({"_id": ObjectId(session["user_id"])})
        advisor_name = advisor.get("fullName", "Unknown Advisor")

        # Fetch client link
        client_link = clients_col.find_one({"_id": ObjectId(client_id)})
        if not client_link:
            return jsonify(ok=False, message="Client link not found"), 400

        # Fetch actual client user
        client_user = users_col.find_one({"_id": client_link["user_id"]})
        client_name = client_user.get("fullName", "Unknown Client") if client_user else "Unknown Client"

        advisor_notes_col.insert_one({
            "advisor_id": ObjectId(session["user_id"]),
            "advisor_name": advisor_name,
            "client_user_id": client_link["user_id"],   # REAL user id
            "client_name": client_name,
            "note": data["notes"],
            "created_at": datetime.utcnow(),
        })

        # Notify client
        notifications_col.insert_one({
            "user_id": client_link["user_id"],
            "message": f"Your advisor added a new note: {data['notes']}",
            "type": "advisor_note",
            "created_at": datetime.utcnow(),
            "read": False
        })

    return jsonify(ok=True, message="Settings saved.")



@app.route("/api/advisor/update_client_budget_limit", methods=["POST"])
@login_required
def api_update_client_budget_limit():
    """
    Advisor actually edits client budget limit (only if client granted permission).
    """
    if session.get("role") != "Financial Advisor":
        return jsonify({"ok": False, "message": "Unauthorized"}), 403

    data = request.get_json(silent=True) or {}
    client_id = data.get("client_id")
    new_limit = data.get("limit")

    if client_id is None or new_limit is None:
        return jsonify({"ok": False, "message": "client_id and limit required"}), 400

    try:
        new_limit = float(new_limit)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "message": "Invalid limit value"}), 400

    if new_limit < 0:
        return jsonify({"ok": False, "message": "Limit must be non-negative"}), 400

    link, error = _get_advisor_client_link(client_id, require_accepted=True)
    if error:
        return error

    if link.get("budget_edit_status") != "granted":
        return jsonify({
            "ok": False,
            "message": "Budget edit permission not granted by client"
        }), 403

    client_user_obj_id = link["user_id"]

    users_col.update_one(
        {"_id": client_user_obj_id},
        {"$set": {"spending_limit": new_limit}}
    )

    # Recalc overspending flag for that client
    recalc_spending_flag_for_user(str(client_user_obj_id))

    return jsonify({"ok": True, "limit": float(new_limit)})

@app.route("/api/user/advisor_notes")
@login_required
def api_user_advisor_notes():
    """Return all advisor notes LEFT FOR THE LOGGED-IN USER."""
    user_id_str = session.get("user_id")

    try:
        user_obj_id = ObjectId(user_id_str)
    except Exception:
        return jsonify({"ok": False, "message": "Invalid user id"}), 400

    # Find all notes where the user is the TARGET
    notes = list(advisor_notes_col.find({
        "client_user_id": user_obj_id
    }).sort("created_at", -1))

    formatted = []
    for n in notes:
        formatted.append({
            "advisor": n.get("advisor_name", "Advisor"),
            "note": n.get("note", ""),
            "created_at": (
                n["created_at"].isoformat()
                if n.get("created_at") else None
            )
        })

    return jsonify({"ok": True, "notes": formatted})


@app.route("/api/advisor/notes/<client_id>")
@login_required
def api_advisor_notes(client_id):
    if session.get("role") != "Financial Advisor":
        return jsonify({"ok": False, "message": "Unauthorized"}), 403

    try:
        client_obj_id = ObjectId(client_id)
    except Exception:
        return jsonify({"ok": False, "message": "Invalid client id"}), 400

    advisor_id = ObjectId(session["user_id"])

    notes = list(advisor_notes_col.find({
        "advisor_id": advisor_id,
        "client_user_id": client_obj_id
    }).sort("created_at", -1))

    formatted = []
    for n in notes:
        formatted.append({
            "advisor": n.get("advisor_name"),
            "client": n.get("client_name"),
            "note": n.get("note"),
            "created_at": (
                n["created_at"].isoformat()
                if n.get("created_at") else None
            )
        })

    return jsonify({"ok": True, "notes": formatted})

@app.route("/api/user/update_spending_limit", methods=["POST"])
@login_required
def api_update_spending_limit():
    data = request.get_json(silent=True) or {}
    new_limit = data.get("limit")

    print("== UPDATE SPENDING LIMIT ==")
    print("SESSION USER:", session.get("user_id"))

    if new_limit is None:
        return jsonify({"ok": False, "message": "Limit required"}), 400

    try:
        new_limit = float(new_limit)
    except:
        return jsonify({"ok": False, "message": "Invalid limit value"}), 400

    user_id = session.get("user_id")

    users_col.update_one(
        {"_id": ObjectId(user_id)},
        {"$set": {"spending_limit": new_limit}}
    )

    recalc_spending_flag_for_user(user_id)

    print("LIMIT UPDATED TO:", new_limit)

    return jsonify({
        "ok": True,
        "limit": new_limit,
        "message": "Spending limit updated"
    })



from bson import ObjectId, errors as bson_errors  # keep this import

@app.route("/api/advisor/set_priority", methods=["POST"])
@login_required
def advisor_set_priority():
    if session.get("role") != "Financial Advisor":
        return jsonify({"ok": False, "message": "Unauthorized"}), 403

    data = request.get_json(silent=True) or {}
    client_id = data.get("client_id")
    priority = str(data.get("priority", "")).lower()

    if not client_id or priority not in ("low", "medium", "high"):
        return jsonify({"ok": False, "message": "Invalid data"}), 400

    try:
        client_obj_id = ObjectId(client_id)
    except bson_errors.InvalidId:
        return jsonify({"ok": False, "message": "Invalid client_id"}), 400

    advisor_id_str = session.get("user_id")
    try:
        advisor_id = ObjectId(advisor_id_str)
    except bson_errors.InvalidId:
        return jsonify({"ok": False, "message": "Invalid advisor id"}), 400

    try:
        result = clients_col.update_one(
            {"_id": client_obj_id, "advisor_id": advisor_id},
            {"$set": {"priority": priority}}
        )

        if result.modified_count == 0:
            return jsonify({"ok": False, "message": "Client not found"}), 404

        return jsonify({"ok": True, "message": "Priority updated"})

    except Exception as e:
        print("DB ERROR:", e)
        return jsonify({"ok": False, "message": "DB error"}), 500
    
    #add client route 
    
@app.route("/api/advisor/add_client", methods=["POST"])
@login_required
def api_advisor_add_client():
    if session.get("role") != "Financial Advisor":
        return jsonify({"ok": False, "message": "Unauthorized"}), 403

    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()

    if not email:
        return jsonify({"ok": False, "message": "Email is required"}), 400

    # Find user by email
    user = users_col.find_one({"email": email})
    if not user:
        return jsonify({"ok": False, "message": "No user with that email was found"}), 404

    advisor_id_str = session.get("user_id")
    try:
        advisor_id = ObjectId(advisor_id_str)
    except Exception:
        return jsonify({"ok": False, "message": "Invalid advisor id"}), 400

    # Avoid duplicates: one advisor-client link per user
    existing = clients_col.find_one({
        "advisor_id": advisor_id,
        "user_id": user["_id"],
    })
    if existing:
        return jsonify({"ok": False, "message": "This client is already on your list"}), 409

    now = datetime.utcnow()

    # This row *is* the permission request:
    # status = "Pending"  → waiting for client to accept/decline
    client_doc = {
        "user_id": user["_id"],
        "advisor_id": advisor_id,
        "priority": "low",
        "status": "Pending",
        "notes": "",
        "created_at": now,
        "permission_requested_at": now,
        "permission_updated_at": None,
    }

    result = clients_col.insert_one(client_doc)
    client_doc["_id"] = result.inserted_id

    client_payload = {
        "_id": str(client_doc["_id"]),
        "full_name": user.get("fullName", "Unknown"),
        "email": user.get("email", ""),
        "status": client_doc["status"],
        "priority": client_doc["priority"],
    }

    return jsonify({
        "ok": True,
        "message": "Permission request sent to client",
        "client": client_payload
    }), 201


#Delete client route
@app.route("/api/advisor/clients/<client_id>", methods=["DELETE"])
@login_required
def api_advisor_delete_client(client_id):
    if session.get("role") != "Financial Advisor":
        return jsonify({"ok": False, "message": "Unauthorized"}), 403

    advisor_id_str = session.get("user_id")
    try:
        advisor_id = ObjectId(advisor_id_str)
        client_obj_id = ObjectId(client_id)
    except bson_errors.InvalidId:
        return jsonify({"ok": False, "message": "Invalid id"}), 400

    result = clients_col.delete_one({
        "_id": client_obj_id,
        "advisor_id": advisor_id
    })

    if result.deleted_count == 0:
        return jsonify({"ok": False, "message": "Client not found"}), 404

    return jsonify({"ok": True})


@app.route("/advisor_settings")
def advisor_settings_page():
    if "user_id" not in session:
        return redirect("/")
    return render_template("advisor-settings.html")

# -----------------------------------------
# CLIENT NOTIFICATIONS: ADVISOR REQUESTS
# -----------------------------------------

@app.route("/api/client/requests")
@login_required
def api_client_requests():
    """Return pending advisor->client links for the logged-in user."""
    user_id_str = session.get("user_id")
    try:
        user_obj_id = ObjectId(user_id_str)
    except Exception:
        return jsonify({"ok": False, "message": "Invalid user id"}), 400

    links = list(clients_col.find({
        "user_id": user_obj_id,
        "status": "Pending",
        "advisor_id": {"$ne": None}  # ignore the default row with advisor_id None
    }))

    requests_out = []
    for link in links:
        advisor = users_col.find_one({"_id": link["advisor_id"]})
        advisor_name = advisor.get("fullName", "Unknown Advisor") if advisor else "Unknown Advisor"
        requests_out.append({
            "id": str(link["_id"]),          # client link id (NOT the user id)
            "advisorName": advisor_name
        })

    return jsonify({"ok": True, "requests": requests_out})


@app.route("/api/client/requests/respond", methods=["POST"])
@login_required
def api_client_requests_respond():
    """Client accepts/declines an advisor link (permission request)."""
    data = request.get_json(silent=True) or {}
    link_id = data.get("id")
    decision = (data.get("decision") or "").lower()

    if decision not in ("accept", "decline"):
        return jsonify({"ok": False, "message": "Invalid decision"}), 400

    user_id_str = session.get("user_id")
    try:
        user_obj_id = ObjectId(user_id_str)
        link_obj_id = ObjectId(link_id)
    except Exception:
        return jsonify({"ok": False, "message": "Invalid id"}), 400

    # Ensure this link really belongs to the logged-in client
    link = clients_col.find_one({"_id": link_obj_id, "user_id": user_obj_id})
    if not link:
        return jsonify({"ok": False, "message": "Request not found"}), 404

    new_status = "Accepted" if decision == "accept" else "Declined"

    clients_col.update_one(
        {"_id": link_obj_id},
        {"$set": {
            "status": new_status,
            "permission_updated_at": datetime.utcnow()
        }}
    )

    return jsonify({"ok": True, "status": new_status})

@app.route("/api/client/budget_limit_requests")
@login_required
def api_client_budget_limit_requests():
    """
    Client sees pending 'edit budget limit' requests from advisors.
    """
    user_id_str = session.get("user_id")
    try:
        user_obj_id = ObjectId(user_id_str)
    except Exception:
        return jsonify({"ok": False, "message": "Invalid user id"}), 400

    links = list(clients_col.find({
        "user_id": user_obj_id,
        "budget_edit_status": "pending",
        "advisor_id": {"$ne": None},
    }))

    user = users_col.find_one({"_id": user_obj_id})
    current_limit = float(user.get("spending_limit", DEFAULT_SPENDING_LIMIT)) if user else DEFAULT_SPENDING_LIMIT

    requests_out = []
    for link in links:
        advisor = users_col.find_one({"_id": link["advisor_id"]})
        advisor_name = advisor.get("fullName", "Unknown Advisor") if advisor else "Unknown Advisor"
        requests_out.append({
            "id": str(link["_id"]),          # client-link id
            "advisorName": advisor_name,
            "currentLimit": current_limit,
        })

    return jsonify({"ok": True, "requests": requests_out})


@app.route("/api/client/budget_limit_requests/respond", methods=["POST"])
@login_required
def api_client_budget_limit_requests_respond():
    """
    Client accepts / declines budget edit request.
    """
    data = request.get_json(silent=True) or {}
    link_id = data.get("id")
    decision = (data.get("decision") or "").lower()

    if decision not in ("accept", "decline"):
        return jsonify({"ok": False, "message": "Invalid decision"}), 400

    user_id_str = session.get("user_id")
    try:
        user_obj_id = ObjectId(user_id_str)
        link_obj_id = ObjectId(link_id)
    except Exception:
        return jsonify({"ok": False, "message": "Invalid id"}), 400

    link = clients_col.find_one({"_id": link_obj_id, "user_id": user_obj_id})
    if not link:
        return jsonify({"ok": False, "message": "Request not found"}), 404

    new_status = "granted" if decision == "accept" else "denied"

    clients_col.update_one(
        {"_id": link_obj_id},
        {"$set": {
            "budget_edit_status": new_status,
            "budget_edit_updated_at": datetime.utcnow(),
        }},
    )

    return jsonify({"ok": True, "status": new_status})

# ---------------------------
# BANK / PLAID API ENDPOINTS
# ---------------------------

@app.route("/api/bank/connect-sandbox", methods=["POST"])
@login_required
def api_bank_connect_sandbox():
    user_id = session.get("user_id")
    user = users_col.find_one({"_id": ObjectId(user_id)})
    if not user:
        return jsonify({"ok": False, "message": "User not found"}), 404

    email = (user.get("email") or "").strip().lower()
    if not email:
        return jsonify({"ok": False, "message": "Missing email"}), 400

    try:
        sandbox_creds = create_sandbox_access_token()
        access_token = sandbox_creds["access_token"]
        item_id = sandbox_creds["item_id"]

        balances_raw = get_current_balances(access_token)
        tx_raw = get_recent_transactions(access_token, days=30, count=100)

        total_balance = _compute_total_balance(balances_raw)
        recent_tx = _simplify_transactions(tx_raw)

        bank_accounts_col.update_one(
            {"user_id": user_id},
            {"$set": {
                "user_id": user_id,
                "email": email,
                "access_token": access_token,
                "item_id": item_id,
                "current_balance": float(total_balance),
                "recent_transactions": recent_tx,
                "updated_at": datetime.utcnow(),
            }},
            upsert=True,
        )

        return jsonify({
            "ok": True,
            "connected": True,
            "current_balance": float(total_balance),
            "recent_transactions": recent_tx
        })

    except Exception as e:
        print("BANK CONNECT ERROR:", e)
        return jsonify({"ok": False, "message": "Failed to connect sandbox bank"}), 500


@app.route("/api/bank/status")
@login_required
def api_bank_status():
    user_id = session.get("user_id")
    doc = bank_accounts_col.find_one({"user_id": user_id})

    if not doc:
        return jsonify({"ok": True, "connected": False})

    access_token = doc.get("access_token")
    if not access_token:
        bank_accounts_col.delete_one({"_id": doc["_id"]})
        return jsonify({"ok": True, "connected": False})

    try:
        balances_raw = get_current_balances(access_token)
        tx_raw = get_recent_transactions(access_token, days=30, count=100)

        total_balance = _compute_total_balance(balances_raw)
        recent_tx = _simplify_transactions(tx_raw)

        update = {
            "current_balance": float(total_balance),
            "recent_transactions": recent_tx,
            "updated_at": datetime.utcnow(),
        }

        bank_accounts_col.update_one({"_id": doc["_id"]}, {"$set": update})
        doc.update(update)

        return jsonify({
            "ok": True,
            "connected": True,
            "current_balance": doc["current_balance"],
            "recent_transactions": doc["recent_transactions"],
        })

    except Exception as e:
        print("BANK STATUS ERROR:", e)
        return jsonify({
            "ok": True,
            "connected": True,
            "current_balance": doc.get("current_balance"),
            "recent_transactions": doc.get("recent_transactions", []),
            "warning": "Failed refresh – using cached",
        })


@app.route("/api/bank/disconnect", methods=["POST"])
@login_required
def api_bank_disconnect():
    user_id = session.get("user_id")
    bank_accounts_col.delete_one({"user_id": user_id})
    return jsonify({"ok": True, "connected": False})


@app.route("/api/compliance/plaid-overview")
@login_required
def api_compliance_plaid_overview():
    """
    System-level view of Plaid-connected accounts.
    Only Compliance Regulators can access this.
    """
    if session.get("role") != "Compliance Regulator":
        return jsonify({"ok": False, "message": "Unauthorized"}), 403

    accounts = list(bank_accounts_col.find({}))
    overview = []
    total_balance = 0.0

    for doc in accounts:
        user_id_str = doc.get("user_id")
        user_doc = None
        if user_id_str:
            try:
                user_doc = users_col.find_one({"_id": ObjectId(user_id_str)})
            except Exception:
                user_doc = None

        current_balance = float(doc.get("current_balance") or 0.0)
        total_balance += current_balance

        overview.append({
            "user_id": user_id_str,
            "email": (user_doc or {}).get("email"),
            "role": normalize_role((user_doc or {}).get("role")),
            "current_balance": current_balance,
            "last_updated": (
                doc.get("updated_at").isoformat()
                if isinstance(doc.get("updated_at"), datetime)
                else None
            ),
            "num_recent_transactions": len(doc.get("recent_transactions", [])),
        })

    return jsonify({
        "ok": True,
        "total_connected_users": len(overview),
        "total_system_balance": round(total_balance, 2),
        "accounts": overview,
    })

# Retention policy api's
@app.route("/api/user/delete_bank_data", methods=["POST"])
@login_required
def api_user_delete_bank_data():
    """
    Allow the logged-in user to permanently delete their own bank data
    (Plaid connection + compliance mirror of transactions).
    """
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"ok": False, "message": "Not logged in"}), 401

    # Delete Plaid connection & cached transactions
    bank_result = bank_accounts_col.delete_many({"user_id": user_id})

    # Delete compliance mirror of this user's transactions (if any)
    tx_result = transactions_col.delete_many({"user_id": user_id})

    return jsonify({
        "ok": True,
        "message": "Bank data deleted",
        "deleted": {
            "bank_accounts": bank_result.deleted_count,
            "compliance_transactions": tx_result.deleted_count,
        }
    })



@app.route("/api/compliance/retention/bank-data", methods=["POST"])
@login_required
def api_compliance_retention_bank_data():
    """
    Retention policy API for bank data.

    Only 'Compliance Regulator' can call this.

    Payload examples:

    - Delete a single user's bank data:
      { "mode": "user", "user_id": "<user_id_string>" }

    - Delete data older than 365 days:
      { "mode": "age", "older_than_days": 365 }

    - Delete ALL bank data (dangerous / audit-protected):
      { "mode": "all" }
    """
    if session.get("role") != "Compliance Regulator":
        return jsonify({"ok": False, "message": "Unauthorized"}), 403

    data = request.get_json(silent=True) or {}
    mode = (data.get("mode") or "user").lower()

    deleted = {
        "bank_accounts": 0,
        "compliance_transactions": 0,
    }

    # ---------------------------
    # MODE: delete by user_id
    # ---------------------------
    if mode == "user":
        user_id = data.get("user_id")
        if not user_id:
            return jsonify({"ok": False, "message": "user_id required for mode='user'"}), 400

        bank_res = bank_accounts_col.delete_many({"user_id": user_id})
        tx_res = transactions_col.delete_many({"user_id": user_id})

        deleted["bank_accounts"] = bank_res.deleted_count
        deleted["compliance_transactions"] = tx_res.deleted_count

    # ---------------------------
    # MODE: delete by age
    # ---------------------------
    elif mode == "age":
        try:
            older_than_days = int(data.get("older_than_days", 365))
        except (TypeError, ValueError):
            return jsonify({"ok": False, "message": "older_than_days must be an integer"}), 400

        cutoff = datetime.utcnow() - timedelta(days=older_than_days)

        # bank_accounts_col uses updated_at for freshness
        bank_res = bank_accounts_col.delete_many({
            "updated_at": {"$lt": cutoff}
        })

        # transactions_col also has updated_at
        tx_res = transactions_col.delete_many({
            "updated_at": {"$lt": cutoff}
        })

        deleted["bank_accounts"] = bank_res.deleted_count
        deleted["compliance_transactions"] = tx_res.deleted_count

    # ---------------------------
    # MODE: delete everything
    # ---------------------------
    elif mode == "all":
        bank_res = bank_accounts_col.delete_many({})
        tx_res = transactions_col.delete_many({})

        deleted["bank_accounts"] = bank_res.deleted_count
        deleted["compliance_transactions"] = tx_res.deleted_count

    else:
        return jsonify({"ok": False, "message": "Invalid mode. Use 'user', 'age', or 'all'."}), 400

    return jsonify({
        "ok": True,
        "mode": mode,
        "deleted": deleted
    })

#retention policies end


# ---------------------------
# REGISTER
# ---------------------------

@app.route("/api/register", methods=["POST"])
def api_register():
    data = request.get_json(silent=True) or {}

    full_name = (data.get("fullName") or data.get("fullname") or "").strip()
    username = (data.get("username") or "").strip().lower()
    email = (data.get("email") or "").strip().lower()
    password = (data.get("password") or "")
    role = normalize_role(data.get("role"))

    if not full_name or " " not in full_name:
        return jsonify({"ok": False, "message": "Enter your full name"}), 400
    if not username or len(username) < 3:
        return jsonify({"ok": False, "message": "Username too short"}), 400
    if not email:
        return jsonify({"ok": False, "message": "Email required"}), 400
    if len(password) < 8:
        return jsonify({"ok": False, "message": "Password must be 8+ characters"}), 400

    existing = users_col.find_one({
        "$or": [{"email": email}, {"username": username}]
    })
    if existing:
        return jsonify({"ok": False, "message": "Email or username already exists"}), 409

    pw_hash = hash_password(password)

    user_doc = {
        "fullName": full_name,
        "username": username,
        "email": email,
        "password_hash": pw_hash,
        "role": role,
        "totp_secret": None,
        "twofa_enabled": False,
        "created_at": datetime.utcnow(),
    }

    result = users_col.insert_one(user_doc)

    # ------------------------------
    # INSERT NEW USER INTO CLIENTS DB
    # ------------------------------
    clients_col.insert_one({
        "user_id": result.inserted_id,
        "advisor_id": None,
        "status": "Pending",
        "priority": "Low",
        "notes": "",
        "created_at": datetime.utcnow()
    })

    session.clear()
    session["user_id"] = str(result.inserted_id)
    session["identifier"] = email or username
    session["role"] = role

       # Decide where to send the user after registration based on role
    if role == "Financial Advisor":
        redirect_url = "/advisor_dashboard"
    elif role == "Compliance Regulator":
        redirect_url = "/compliance-dashboard.html"
    else:
        redirect_url = "/dashboard.html"

    return jsonify({"ok": True, "redirect": redirect_url}), 201




# ---------------------------
# LOGIN (with 2FA)
# ---------------------------

@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.get_json(silent=True) or {}
    identifier = (data.get("identifier") or "").strip()
    password = (data.get("password") or "")

    invalid_msg = "Invalid credentials."

    # Optional ?next=... for deep links
    next_url = data.get("next") or request.args.get("next") or ""
    next_url = next_url if _is_safe_url(next_url) else ""

    user = find_user_by_identifier(identifier)
    if not user or not verify_password(password, user.get("password_hash", "")):
        return jsonify({"ok": False, "message": invalid_msg}), 401

    # If 2FA is enabled, go into "pending" state
    if user.get("twofa_enabled") and user.get("totp_secret"):
        session.clear()
        session["pending_2fa_user_id"] = str(user["_id"])
        session["pending_next"] = next_url
        return jsonify({"ok": True, "require_2fa": True})

    # Normal login flow (no 2FA)
    session.clear()
    session["user_id"] = str(user["_id"])
    session["identifier"] = user.get("email") or user.get("username")
    user_role = normalize_role(user.get("role"))
    session["role"] = user_role

    # Decide post-login destination by role / simp_dash
    if _is_safe_url(next_url):
        redirect_to = next_url
    elif user_role == "Financial Advisor":
        redirect_to = "/advisor_dashboard"
    elif user_role == "Compliance Regulator":
        redirect_to = "/compliance-dashboard.html"
    else:
        # Regular user → use helper that checks simp_dash / dashboard_mode
        redirect_to = get_dashboard_redirect_for(user)

    return jsonify({"ok": True, "require_2fa": False, "redirect": redirect_to})


# ---------------------------
# VERIFY 2FA
# ---------------------------

@app.route("/api/verify-2fa", methods=["POST"])
def api_verify_2fa():
    user_id = session.get("pending_2fa_user_id")
    if not user_id:
        return jsonify({"ok": False, "message": "No verification in progress"}), 400

    user = users_col.find_one({"_id": ObjectId(user_id)})
    if not user or not user.get("twofa_enabled") or not user.get("totp_secret"):
        session.pop("pending_2fa_user_id", None)
        session.pop("pending_next", None)
        return jsonify({"ok": False, "message": "2FA not configured"}), 400

    data = request.get_json(silent=True) or {}
    code = (data.get("code") or "").strip()

    if not (code.isdigit() and len(code) == 6):
        return jsonify({"ok": False, "message": "Invalid code"}), 400

    totp = pyotp.TOTP(user["totp_secret"])
    if not totp.verify(code, valid_window=1):
        return jsonify({"ok": False, "message": "Incorrect or expired code"}), 401

    # 2FA success → establish full session
    session["user_id"] = str(user["_id"])
    session["identifier"] = user.get("email") or user.get("username")
    user_role = normalize_role(user.get("role"))
    session["role"] = user_role

    next_url = session.pop("pending_next", "")
    session.pop("pending_2fa_user_id", None)

    # Same redirect rules as normal login
    if _is_safe_url(next_url):
        redirect_to = next_url
    elif user_role == "Financial Advisor":
        redirect_to = "/advisor_dashboard"
    elif user_role == "Compliance Regulator":
        redirect_to = "/compliance-dashboard.html"
    else:
        redirect_to = get_dashboard_redirect_for(user)

    return jsonify({"ok": True, "redirect": redirect_to})


@app.route("/api/2fa-status")
@login_required
def api_2fa_status():
    user_id = session.get("user_id")
    user = users_col.find_one({"_id": ObjectId(user_id)})
    if not user:
        return jsonify({"ok": False}), 404

    enabled = bool(user.get("twofa_enabled") and user.get("totp_secret"))
    qr_b64 = None
    secret = None

    if enabled:
        otp_uri = pyotp.TOTP(user["totp_secret"]).provisioning_uri(
            name=user["email"],
            issuer_name="BudgetMind AI"
        )
        qr_img = qrcode.make(otp_uri)
        buf = io.BytesIO()
        qr_img.save(buf, format="PNG")
        qr_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
        secret = user["totp_secret"]

    return jsonify({
        "ok": True,
        "enabled": enabled,
        "qrCode": f"data:image/png;base64,{qr_b64}" if qr_b64 else None,
        "secret": secret
    })


@app.route("/api/setup-2fa", methods=["POST"])
@login_required
def api_setup_2fa():
    user_id = session.get("user_id")
    user = users_col.find_one({"_id": ObjectId(user_id)})
    if not user:
        return jsonify({"ok": False}), 404

    if user.get("twofa_enabled") and user.get("totp_secret"):
        return jsonify({"ok": True, "message": "Already enabled"})

    secret = pyotp.random_base32()
    users_col.update_one(
        {"_id": user["_id"]},
        {"$set": {"twofa_enabled": True, "totp_secret": secret}}
    )

    otp_uri = pyotp.TOTP(secret).provisioning_uri(
        name=user["email"],
        issuer_name="BudgetMind AI"
    )
    qr_img = qrcode.make(otp_uri)
    buf = io.BytesIO()
    qr_img.save(buf, format="PNG")
    qr_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

    return jsonify({
        "ok": True,
        "qrCode": f"data:image/png;base64,{qr_b64}",
        "secret": secret
    })


@app.route("/api/disable-2fa", methods=["POST"])
@login_required
def api_disable_2fa():
    user_id = session.get("user_id")
    users_col.update_one(
        {"_id": ObjectId(user_id)},
        {"$set": {"twofa_enabled": False, "totp_secret": None}}
    )
    return jsonify({"ok": True})


# ---------------------------
# PROFILE & AVATAR
# ---------------------------

@app.route("/api/profile-picture/<user_id>")
@login_required
def api_get_profile_picture(user_id):
    pic = profile_pics_col.find_one({"user_id": user_id})
    if not pic:
        return jsonify({"ok": False, "message": "No picture"}), 404

    return jsonify({
        "ok": True,
        "image": f"data:image/png;base64,{pic['image']}"
    })


@app.route("/api/update-profile", methods=["POST"])
@login_required
def api_update_profile():
    user_id = session.get("user_id")
    data = request.form.to_dict()
    file = request.files.get("profilePic")

    update_fields = {}

    if data.get("fullName"):
        update_fields["fullName"] = data["fullName"].strip()

    if data.get("username"):
        update_fields["username"] = data["username"].strip().lower()

    if data.get("email"):
        update_fields["email"] = data["email"].strip().lower()

    if data.get("newPassword"):
        update_fields["password_hash"] = hash_password(data["newPassword"])

    if file and file.filename != "":
        image_bytes = file.read()
        encoded = base64.b64encode(image_bytes).decode("utf-8")

        profile_pics_col.delete_many({"user_id": user_id})
        profile_pics_col.insert_one({
            "user_id": user_id,
            "image": encoded,
            "updated_at": datetime.utcnow()
        })

    if update_fields:
        users_col.update_one({"_id": ObjectId(user_id)}, {"$set": update_fields})

    updated_user = users_col.find_one({"_id": ObjectId(user_id)}, {"password_hash": 0})
    updated_user["_id"] = str(updated_user["_id"])

    return jsonify({"ok": True, "user": updated_user})


# ---------------------------
# ADVISOR API
# ---------------------------

@app.route("/api/advisor/summary")
@login_required
def api_advisor_summary():
    if session.get("role") != "Financial Advisor":
        return jsonify({"ok": False, "message": "Unauthorized"}), 403

    client_link_id = request.args.get("client")  # clients_col _id
    time_range = request.args.get("range", "month")

    if not client_link_id:
        return jsonify({"ok": False, "message": "Missing client id"}), 400

    # Must belong to this advisor AND be Accepted
    link, error = _get_advisor_client_link(client_link_id, require_accepted=True)
    if error:
        return error

    client_user_obj_id = link.get("user_id")
    if not client_user_obj_id:
        return jsonify({"ok": False, "message": "Client user missing"}), 400

    client_user_id_str = str(client_user_obj_id)

    # Time window based on range
    days_map = {"month": 30, "quarter": 90, "year": 365}
    days = days_map.get(time_range, 30)
    cutoff = datetime.utcnow().date() - timedelta(days=days)

    # PLAID ONLY
    bank_doc = bank_accounts_col.find_one({"user_id": client_user_id_str})
    if not bank_doc or not bank_doc.get("recent_transactions"):
        return jsonify({
            "ok": True,
            "hasData": False,
            "labels": [],
            "income": [],
            "expenses": [],
            "categoryBreakdown": {},
            "transactions": [],
        })

    txs = bank_doc.get("recent_transactions", [])
    summary = _build_plaid_summary(txs, cutoff)

    if not summary["labels"]:
        summary.update({
            "ok": True,
            "hasData": False,
        })
    else:
        summary.update({
            "ok": True,
            "hasData": True,
        })

    return jsonify(summary)



def _build_plaid_summary(txs, cutoff_date):
    """
    Build summary from Plaid transactions only.
    txs: list of dicts with keys: date, name, category, amount, transaction_id, ...
    cutoff_date: date object; only include txs >= cutoff_date.
    """
    filtered = []

    # Filter by date
    for tx in txs:
        raw_date = tx.get("date")
        if isinstance(raw_date, datetime):
            d = raw_date.date()
        else:
            try:
                d = datetime.fromisoformat(str(raw_date)).date()
            except Exception:
                try:
                    d = datetime.strptime(str(raw_date), "%Y-%m-%d").date()
                except Exception:
                    continue

        if d < cutoff_date:
            continue

        filtered.append((d, tx))

    # Sort ascending by date
    filtered.sort(key=lambda x: x[0])

    income_by_day = {}
    expense_by_day = {}
    categories = {}
    tx_output = []

    for d, tx in filtered:
        amt_raw = float(tx.get("amount") or 0)
        name = tx.get("name", "")
        cat = tx.get("category") or "Other"

        # Use your existing classifier to decide income vs expense
        is_income = _classify_direction(name, cat)
        signed = amt_raw if is_income else -amt_raw
        date_key = d.isoformat()

        if signed >= 0:
            income_by_day[date_key] = income_by_day.get(date_key, 0.0) + signed
        else:
            val = abs(signed)
            expense_by_day[date_key] = expense_by_day.get(date_key, 0.0) + val
            categories[cat] = categories.get(cat, 0.0) + val

        tx_output.append({
            "date": date_key,
            "name": name,
            "category": cat,
            "amount": signed,
            "transaction_id": tx.get("transaction_id"),
        })

    labels = sorted(set(list(income_by_day.keys()) + list(expense_by_day.keys())))
    income_list = [round(income_by_day.get(d, 0.0), 2) for d in labels]
    expense_list = [round(expense_by_day.get(d, 0.0), 2) for d in labels]

    return {
        "labels": labels,
        "income": income_list,
        "expenses": expense_list,
        "categoryBreakdown": {k: round(v, 2) for k, v in categories.items()},
        "transactions": tx_output,
    }
# ---------------------------
# FORGOT PASSWORD
# ---------------------------

@app.route("/api/forgot_password", methods=["POST"])
def api_forgot_password():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    new_password = (data.get("newPassword") or "").strip()

    if not email or not new_password:
        return jsonify({"ok": False, "message": "Email and new password required"}), 400

    user = users_col.find_one({"email": email})
    if not user:
        return jsonify({"ok": False, "message": "No account found"}), 404

    pw_hash = hash_password(new_password)
    users_col.update_one({"_id": user["_id"]}, {"$set": {"password_hash": pw_hash}})

    return jsonify({"ok": True, "message": "Password updated"})


# ---------------------------
# SUMMARY: INCOME VS EXPENSE
# ---------------------------

@app.route("/api/summary")
@login_required
def api_summary():
    user_id = session.get("user_id")
    bank_doc = bank_accounts_col.find_one({"user_id": user_id})

    # Prefer Plaid
    if bank_doc and bank_doc.get("recent_transactions"):
        txs = bank_doc["recent_transactions"]
        income = 0.0
        expense = 0.0
        categories = {}

        for tx in txs:
            amt = float(tx.get("amount") or 0)

            name = tx.get("name", "")
            cat = tx.get("category", "Other")
            is_income = _classify_direction(name, cat)

            signed = amt if is_income else -amt

            if signed > 0:
                income += signed
            else:
                value = abs(signed)
                expense += value
                categories[cat] = categories.get(cat, 0.0) + value

        sorted_list = sorted(
            [{"name": c, "total": t} for c, t in categories.items()],
            key=lambda x: x["total"],
            reverse=True
        )

        return jsonify({
            "income": float(income),
            "expense": float(expense),
            "categories": sorted_list
        })

    # fallback to manual entries
    entries = list(entries_col.find({"user_id": user_id}))
    income = sum(float(e.get("amount", 0)) for e in entries if e.get("type") == "income")
    expense = sum(float(e.get("amount", 0)) for e in entries if e.get("type") == "expense")

    cat_totals = {}
    for e in entries:
        if e.get("type") == "expense":
            cat = str(e.get("category", "Other")).title()
            cat_totals[cat] = cat_totals.get(cat, 0.0) + float(e.get("amount", 0))

    sorted_list = sorted(
        [{"name": c, "total": t} for c, t in cat_totals.items()],
        key=lambda x: x["total"],
        reverse=True
    )

    return jsonify({
        "income": float(income),
        "expense": float(expense),
        "categories": sorted_list
    })


# ---------------------------
# MANUAL ENTRY
# ---------------------------

@app.route("/entry", methods=["POST"])
@login_required
def api_add_manual_entry():
    user_id = session.get("user_id")
    t = request.form.get("type")
    cat = request.form.get("category")
    amt = request.form.get("amount")

    if not t or not cat or not amt:
        return jsonify({"ok": False, "message": "Missing fields"}), 400

    try:
        amt = float(amt)
    except:
        return jsonify({"ok": False, "message": "Invalid amount"}), 400

    entry_doc = {
        "user_id": user_id,
        "type": t.lower(),
        "category": cat.strip().title(),
        "amount": amt,
        "created_at": datetime.utcnow()
    }
    entries_col.insert_one(entry_doc)

    if t.lower() == "expense":
        recalc_spending_flag_for_user(user_id)

    return jsonify({"ok": True, "message": "Entry added"}), 201


# ---------------------------
# USER PROFILE API
# ---------------------------

@app.route("/api/user-profile")
@login_required
def api_user_profile():
    user_id = session.get("user_id")
    user = users_col.find_one({"_id": ObjectId(user_id)}, {"password_hash": 0})
    if not user:
        return jsonify({"ok": False}), 404

    user["_id"] = str(user["_id"])
    return jsonify({"ok": True, "user": user})


def get_current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    try:
        return users_col.find_one({"_id": ObjectId(user_id)})
    except Exception:
        return None

@app.route("/api/user/dashboard_mode", methods=["GET"])
@login_required
def api_get_dashboard_mode():
    user = get_current_user()
    if not user:
        return jsonify(ok=False, message="Not logged in"), 401

    # Prefer the boolean flag, fall back to old text field
    simp_flag = bool(user.get("simp_dash"))
    if simp_flag:
        mode = "simplified"
    else:
        mode = (user.get("dashboard_mode") or "full")

    return jsonify(ok=True, mode=mode, simp_dash=simp_flag)


@app.route("/api/user/dashboard_mode", methods=["POST"])
@login_required
def api_set_dashboard_mode():
    user = get_current_user()
    if not user:
        return jsonify(ok=False, message="Not logged in"), 401

    data = request.get_json(silent=True) or {}
    mode = data.get("mode")

    if mode not in ("full", "simplified"):
        return jsonify(ok=False, message="Invalid mode"), 400

    simp_flag = (mode == "simplified")

    users_col.update_one(
        {"_id": user["_id"]},
        {"$set": {
            "dashboard_mode": mode,   # keep for backwards compatibility
            "simp_dash": simp_flag    # new boolean flag
        }}
    )

    return jsonify(ok=True, mode=mode, simp_dash=simp_flag)


# optional alias if your JS calls the old name
@app.route("/api/user/update_dashboard_mode", methods=["POST"])
@login_required
def api_update_dashboard_mode_legacy():
    return api_set_dashboard_mode()

# ---------------------------
# TRANSACTIONS API
# ---------------------------

@app.route("/api/transactions")
@login_required
def api_transactions():
    user_id = session.get("user_id")
    doc = bank_accounts_col.find_one({"user_id": user_id})
    if not doc or not doc.get("recent_transactions"):
        return jsonify({"ok": True, "transactions": []})

    txs = doc["recent_transactions"]
    txs_sorted = sorted(txs, key=lambda x: x.get("date", ""), reverse=True)

    try:
        limit = int(request.args.get("limit", 50))
    except:
        limit = 50

    return jsonify({"ok": True, "transactions": txs_sorted[:limit]})


@app.route("/api/transactions/<tx_id>")
@login_required
def api_transaction_detail(tx_id):
    user_id = session.get("user_id")
    doc = bank_accounts_col.find_one({"user_id": user_id})
    if not doc:
        return jsonify({"ok": False, "message": "No transactions"}), 404

    for tx in doc.get("recent_transactions", []):
        if tx.get("transaction_id") == tx_id:
            return jsonify({"ok": True, "transaction": tx})

    return jsonify({"ok": False, "message": "Not found"}), 404

#----------------------------
# COMPLIANCE API TRANSACTION & FLAGS
#----------------------------

@app.route("/api/compliance/save_transactions", methods=["POST"])
@login_required
def api_save_transactions():
    # Only Compliance Regulators or Advisors can save system-level data
    if session.get("role") not in ["Compliance Regulator", "Financial Advisor"]:
        return jsonify({"ok": False, "message": "Unauthorized"}), 403

    data = request.get_json(silent=True) or {}
    user_id = data.get("user_id")
    transactions = data.get("transactions")

    if not user_id or not isinstance(transactions, list):
        return jsonify({"ok": False, "message": "Invalid payload"}), 400

    # Convert transactions → CSV string
    csv_buffer = StringIO()
    csv_writer = csv.DictWriter(csv_buffer, fieldnames=transactions[0].keys())
    csv_writer.writeheader()
    csv_writer.writerows(transactions)

    csv_string = csv_buffer.getvalue()
    csv_b64 = base64.b64encode(csv_string.encode("utf-8")).decode("utf-8")

    # Store in DB (1 doc per user)
    now = datetime.utcnow()
    transactions_col.update_one(
        {"user_id": user_id},
        {"$set": {
            "user_id": user_id,
            "transactions": transactions,
            "csv_data": csv_b64,
            "updated_at": now,
            "created_at": now
        }},
        upsert=True
    )

    return jsonify({"ok": True, "message": "Transactions saved"})


@app.route("/api/compliance/flag_transaction", methods=["POST"])
@login_required
def api_flag_transaction():
    if session.get("role") != "Compliance Regulator":
        return jsonify({"ok": False, "message": "Unauthorized"}), 403

    tx = request.get_json().get("transaction", {})
    reasons = []
    risk_level = "Low"

    amount = float(tx.get("amount", 0))
    merchant = tx.get("name", "").lower()

    # Rule 1 — High value
    if amount >= 5000:
        reasons.append("Critical: High-value transaction")
        risk_level = "Critical"
    elif amount >= 2000:
        reasons.append("High-value transaction")
        risk_level = "High"

    # Rule 2 — Suspicious merchant categories
    if any(k in merchant for k in ["crypto", "casino", "bet", "gamble"]):
        reasons.append("Suspicious merchant")
        risk_level = "Critical"

    # Rule 3 — Velocity (3+ transactions in last hour)
    now = datetime.utcnow()
    recent = flagged_col.count_documents({
        "transaction.name": tx.get("name"),
        "created_at": {"$gte": now - timedelta(hours=1)}
    })
    if recent >= 3:
        reasons.append("Velocity pattern detected")

    suspicious = len(reasons) > 0

    if suspicious:
        flagged_col.insert_one({
            "transaction": tx,
            "reasons": reasons,
            "risk": risk_level,
            "reported": False,
            "created_at": now
        })

    return jsonify({
        "ok": True,
        "suspicious": suspicious,
        "risk": risk_level,
        "reasons": reasons
    })

@app.route("/api/compliance/summary")
@login_required
def api_compliance_summary():
    if session.get("role") != "Compliance Regulator":
        return jsonify({"ok": False, "message": "Unauthorized"}), 403

    flagged = list(flagged_col.find({}))
    total = len(flagged)

    critical = sum(1 for f in flagged if f.get("risk") == "Critical")
    high = sum(1 for f in flagged if f.get("risk") == "High")
    medium = sum(1 for f in flagged if f.get("risk") == "Medium")
    low = sum(1 for f in flagged if f.get("risk") == "Low")

    return jsonify({
        "ok": True,
        "total_flagged": total,
        "risk_distribution": {
            "critical": critical,
            "high": high,
            "medium": medium,
            "low": low
        },
        "flagged": [
            {
                "merchant": f["transaction"].get("name"),
                "amount": f["transaction"].get("amount"),
                "risk": f.get("risk"),
                "reasons": f.get("reasons")
            }
            for f in flagged
        ]
    })
def get_dashboard_redirect_for(user_doc):
    """
    Returns the URL to send the user to after login / 2FA / re-auth,
    based on simp_dash / dashboard_mode.
    """
    if not user_doc:
        return "/dashboard.html"

    # New boolean flag wins
    if user_doc.get("simp_dash") is True:
        return "/simplified-dashboard.html"

    mode = user_doc.get("dashboard_mode", "full")
    if mode == "simplified":
        return "/simplified-dashboard.html"
    return "/dashboard.html"

@app.route("/api/compliance/flagged")
@login_required
def api_flagged_transactions():
    if session.get("role") != "Compliance Regulator":
        return jsonify({"ok": False, "message": "Unauthorized"}), 403

    flagged = list(flagged_col.find({}).sort("created_at", -1))

    output = []
    for f in flagged:
        output.append({
            "id": str(f["_id"]),
            "transaction": f.get("transaction"),
            "reasons": f.get("reasons"),
            "reported": f.get("reported", False),
            "created_at": f["created_at"].isoformat()
        })

    return jsonify({"ok": True, "flagged": output})

@app.route("/api/compliance/audit_logs")
@login_required
def api_compliance_audit_logs():
    """
    Compliance view of audit logs.

    Optional query params:
      - user_id=<string>  -> filter by a specific user
      - action=<string>   -> filter by action (e.g. "HTTP_API_CALL")
      - limit=<int>       -> max number of logs (1–500, default 100)
    """
    if session.get("role") != "Compliance Regulator":
        return jsonify({"ok": False, "message": "Unauthorized"}), 403

    # Filters
    q = {}
    user_id = request.args.get("user_id")
    action = request.args.get("action")

    if user_id:
        q["user_id"] = user_id
    if action:
        q["action"] = action

    # Limit
    try:
        limit = int(request.args.get("limit", 100))
    except ValueError:
        limit = 100
    limit = max(1, min(limit, 500))

    cursor = audit_logs_col.find(q).sort("timestamp", -1).limit(limit)

    logs = []
    for log in cursor:
        logs.append({
            "id": str(log.get("_id")),
            "timestamp": log.get("timestamp").isoformat() if log.get("timestamp") else None,
            "user_id": log.get("user_id"),
            "role": log.get("role"),
            "action": log.get("action"),
            "ip": log.get("ip"),
            "path": log.get("path"),
            "method": log.get("method"),
            "status": log.get("status"),
            "details": log.get("details", {}),
        })

    return jsonify({"ok": True, "logs": logs})

@app.route("/api/audit_logs/me")
@login_required
def api_my_audit_logs():
    user_id = session.get("user_id")
    try:
        limit = int(request.args.get("limit", 50))
    except ValueError:
        limit = 50
    limit = max(1, min(limit, 200))

    cursor = audit_logs_col.find({"user_id": user_id}).sort("timestamp", -1).limit(limit)

    logs = []
    for log in cursor:
        logs.append({
            "id": str(log.get("_id")),
            "timestamp": log.get("timestamp").isoformat() if log.get("timestamp") else None,
            "action": log.get("action"),
            "path": log.get("path"),
            "method": log.get("method"),
            "status": log.get("status"),
            "details": log.get("details", {}),
        })

    return jsonify({"ok": True, "logs": logs})


# ---------------------------
# NOTES SYSTEM
# ---------------------------

@app.route("/notes")
@login_required
def notes_page():
    user_id = session.get("user_id")
    user_notes = list(notes_col.find({"user_id": user_id}).sort("created_at", -1))
    return render_template("notes.html", notes=user_notes)

@app.route("/api/notifications", methods=["GET"])
@login_required
def api_notifications():
    user_id = session.get("user_id")

    items = list(notifications_col.find({"user_id": user_id}).sort("created_at", -1))

    output = []
    for n in items:
        output.append({
            "id": str(n["_id"]),
            "message": n.get("message", ""),
            "type": n.get("type", ""),
            "created_at": n.get("created_at").isoformat() if n.get("created_at") else None,
            "read": n.get("read", False)
        })

    return jsonify({"ok": True, "notifications": output})



@app.route("/notes/add", methods=["POST"])
@login_required
def notes_add():
    user_id = session.get("user_id")
    title = request.form.get("title", "").strip()
    content = request.form.get("content", "").strip()

    if not title or not content:
        return redirect("/notes")

    notes_col.insert_one({
        "user_id": user_id,
        "title": title,
        "content": content,
        "created_at": datetime.utcnow()
    })
    return redirect("/notes")


@app.route("/notes/delete/<note_id>", methods=["POST"])
@login_required
def notes_delete(note_id):
    notes_col.delete_one({"_id": ObjectId(note_id)})
    return redirect("/notes")


# ---------------------------
# CATEGORY BREAKDOWN API
# ---------------------------

def assign_category(name):
    if not name:
        return "Other"
    n = name.lower()
    if any(k in n for k in ["starbucks", "mcdonald", "pizza", "coffee"]):
        return "Dining"
    if any(k in n for k in ["uber", "lyft", "taxi", "bus"]):
        return "Transport"
    if any(k in n for k in ["airlines", "hotel", "airbnb"]):
        return "Travel"
    if any(k in n for k in ["amazon", "walmart", "target"]):
        return "Shopping"
    if any(k in n for k in ["gym", "fitness", "climb"]):
        return "Fitness"
    if any(k in n for k in ["deposit", "payroll", "credit"]):
        return "Income"
    if any(k in n for k in ["payment", "bill"]):
        return "Bills"
    return "Other"


@app.route("/api/category-breakdown")
@login_required
def api_category_breakdown():
    user_id = session.get("user_id")
    doc = bank_accounts_col.find_one({"user_id": user_id})

    if not doc or not doc.get("access_token"):
        return jsonify([])

    txs = get_recent_transactions(doc["access_token"], days=30).get("transactions", [])
    summary = {}

    for tx in txs:
        name = tx.get("name", "")
        amt = float(tx.get("amount", 0))
        cat = assign_category(name)

        if amt > 0:
            summary[cat] = summary.get(cat, 0) + amt

    breakdown = [{"category": c, "total": round(t, 2)} for c, t in summary.items()]
    breakdown.sort(key=lambda x: x["total"], reverse=True)

    return jsonify(breakdown)


# ---------------------------
# LOGOUT
# ---------------------------

@app.route("/logout", methods=["GET", "POST"])
def logout():
    session.clear()
    if request.method == "POST":
        return jsonify({"ok": True, "redirect": "/"})
    return redirect("/")


# ---------------------------
# RUN APP
# ---------------------------

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)


