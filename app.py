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


@app.route("/")
def login_page():
    return render_template("login.html")


@app.route("/register.html")
def register_page():
    return render_template("register.html")


@app.route("/dashboard.html")
@login_required
def dashboard():
    return render_template("dashboard.html")


@app.route("/compliance-dashboard.html")
@login_required
def compliance_dashboard():
    # Only Compliance Regulators are allowed on this page
    if session.get("role") != "Compliance Regulator":
        return redirect("/dashboard.html")
    return render_template("compliance-dashboard.html")

@app.route("/settings.html")
@login_required
def settings_page():
    return render_template("settings.html")

@app.route("/transaction-details.html")
@login_required
def transaction_details_page():
    return render_template("transaction-details.html")

@app.route("/edit-profile.html")
@login_required
def edit_profile_page():
    return render_template("edit_profile.html")

@app.route("/ai-insights")
@login_required
def ai_insights_page():
    return render_template("ai_insights.html")

@app.route("/compliance/transactions")
@login_required
def transactions_page():
    return render_template("transaction-table.html")


@app.route("/budget-limit")
@login_required
def budget_limit_page():
    return render_template("budget_limit.html")

# Add-entry page (GET)
@app.route("/entry")
@login_required
def entry_page():
    return render_template("entry.html")



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
import os
from openai import OpenAI

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

@app.route("/api/ai-chat", methods=["POST"])
@login_required
def api_ai_chat():
    data = request.get_json(silent=True) or {}
    msg = (data.get("message") or "").strip()

    if not msg:
        return jsonify({"reply": "Please type something to chat!"})

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are BudgetMind AI."},
                {"role": "user", "content": msg}
            ],
            temperature=0.7
        )
        reply = response.choices[0].message.content.strip()

    except Exception as e:
        print("AI Chat error:", e)
        reply = "⚠️ I couldn't reach the AI service right now."

    return jsonify({"reply": reply})

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

    next_url = data.get("next") or request.args.get("next") or ""
    next_url = next_url if _is_safe_url(next_url) else ""

    user = find_user_by_identifier(identifier)
    if not user or not verify_password(password, user.get("password_hash", "")):
        return jsonify({"ok": False, "message": invalid_msg}), 401

    # Handle 2FA
    if user.get("twofa_enabled") and user.get("totp_secret"):
        session.clear()
        session["pending_2fa_user_id"] = str(user["_id"])
        session["pending_next"] = next_url
        return jsonify({"ok": True, "require_2fa": True})

    # Normal login
    session.clear()
    session["user_id"] = str(user["_id"])
    session["identifier"] = user.get("email") or user.get("username")
    user_role = normalize_role(user.get("role"))
    session["role"] = user_role

    # Decide post-login destination by role
    if _is_safe_url(next_url):
        redirect_to = next_url
    elif user_role == "Financial Advisor":
        redirect_to = "/advisor_dashboard"
    elif user_role == "Compliance Regulator":
        redirect_to = "/compliance-dashboard.html"
    else:
        redirect_to = "/dashboard.html"

    return jsonify({"ok": True, "require_2fa": False, "redirect": redirect_to})

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
        redirect_to = "/dashboard.html"

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


