import os
import io
import base64
import qrcode
from functools import wraps
from datetime import datetime, date, timedelta
from urllib.parse import urlparse, urljoin

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


@app.route("/advisor_dashboard")
@login_required
def advisor_dashboard_page():
    if session.get("role") != "Financial Advisor":
        return redirect("/dashboard.html")
    return render_template("advisor_dashboard.html")


@app.route("/advisor_clients")
@login_required
def advisor_clients_page():
    if session.get("role") != "Financial Advisor":
        return redirect("/dashboard.html")
    return render_template("advisor_clients.html")

@app.route("/api/advisor/clients")
@login_required
def api_advisor_clients():
    # Must be a Financial Advisor
    if session.get("role") != "Financial Advisor":
        return jsonify({"ok": False, "message": "Unauthorized"}), 403

    advisor_id_str = session.get("user_id")
    try:
        advisor_obj_id = ObjectId(advisor_id_str)
    except Exception:
        return jsonify({"ok": False, "message": "Invalid advisor id"}), 400

    links = list(clients_col.find({"advisor_id": advisor_obj_id}))

    output = []
    for link in links:
        user_doc = users_col.find_one({"_id": link.get("user_id")})
        if not user_doc:
            continue

        output.append({
            "_id": str(link["_id"]),                 # client-link id (used in URLs + dropdown)
            "user_id": str(user_doc["_id"]),        # actual user id
            "full_name": user_doc.get("fullName", "Unknown"),
            "email": user_doc.get("email", ""),
            "priority": link.get("priority", "low"),
            "status": link.get("status", "Pending"),
            "created_at": (
                link.get("created_at").isoformat()
                if link.get("created_at") else None
            ),
        })

    # 🔥 return bare array so BOTH advisor_clients.js and advisor_summary.js work
    return jsonify(output)



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

    client_doc = {
        "user_id": user["_id"],
        "advisor_id": advisor_id,
        "priority": "low",
        "status": "Pending",
        "notes": "",
        "created_at": datetime.utcnow(),
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
        "message": "Client added successfully",
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
    """Client accepts/declines an advisor link."""
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

    new_status = "Accepted" if decision == "accept" else "Declined"

    clients_col.update_one(
        {"_id": link_obj_id},
        {"$set": {"status": new_status}}
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

    redirect_url = "/advisor_dashboard" if role == "Financial Advisor" else "/dashboard.html"

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

    if user_role == "Financial Advisor":
        redirect_to = "/advisor_dashboard"
    else:
        redirect_to = next_url or "/dashboard.html"

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

    next_url = session.pop("pending_next", "")
    session.pop("pending_2fa_user_id", None)

    redirect_to = next_url if _is_safe_url(next_url) else "/dashboard.html"
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

    advisor_id_str = session.get("user_id")
    try:
        advisor_obj_id = ObjectId(advisor_id_str)
        client_link_obj_id = ObjectId(client_link_id)
    except Exception:
        return jsonify({"ok": False, "message": "Invalid id"}), 400

    # Make sure this client belongs to this advisor
    link = clients_col.find_one({
        "_id": client_link_obj_id,
        "advisor_id": advisor_obj_id,
    })
    if not link:
        return jsonify(
            {"ok": False, "message": "Client not found for this advisor"}
        ), 404

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
        # No Plaid data at all -> tell frontend to show "No data"
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

    # If, after filtering by date, nothing remains -> No Data
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


# ---------------------------
# NOTES SYSTEM
# ---------------------------

@app.route("/notes")
@login_required
def notes_page():
    user_id = session.get("user_id")
    user_notes = list(notes_col.find({"user_id": user_id}).sort("created_at", -1))
    return render_template("notes.html", notes=user_notes)


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


