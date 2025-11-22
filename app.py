import os
import io
import base64
import qrcode
from functools import wraps
from datetime import datetime, date
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

# ---------------------------------------------------------------------------
# Load config
# ---------------------------------------------------------------------------

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

# ---------------------------------------------------------------------------
# Spending limits / flags
# ---------------------------------------------------------------------------
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



DEFAULT_SPENDING_LIMIT = 1000.0  # fallback if user doesn't have their own limit


def recalc_spending_flag_for_user(user_id: str):
    """
    Recalculate a user's total expense and update:
      - user.is_flagged (True/False)
      - user.notes (add 'Spending limit exceeded' once when over limit)
    Currently uses ALL-TIME expenses from entries collection.
    """
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

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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
    """
    Sum current balances across all accounts from Plaid's /accounts/balance/get response.
    """
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
    """
    Very simple heuristic to decide if a transaction is INCOME (True) or EXPENSE (False).
    We then use this to decide + vs - sign for signed_amount.

    Incomes: payroll, deposits, credits, refunds, interest.
    Everything else -> expense.
    """
    label = f"{name or ''} {category or ''}".lower()
    income_keywords = ["payroll", "deposit", "credit", "refund", "interest", "intrst"]
    return any(k in label for k in income_keywords)


def _simplify_transactions(tx_payload: dict):
    """
    Converts Plaid transactions to simplified objects with correct categories.
    Uses:
    - category[]
    - personal_finance_category.primary
    - fallback to Uncategorized
    """

    result = []
    for tx in tx_payload.get("transactions", []):
        # Date fix
        raw_date = tx.get("date")
        if isinstance(raw_date, (date, datetime)):
            date_str = raw_date.isoformat()
        else:
            date_str = str(raw_date)

        # --- CATEGORY FIX ---
        category = None

        # 1. Try normal Plaid category list
        cat_list = tx.get("category") or []
        if isinstance(cat_list, list) and len(cat_list) > 0:
            category = " / ".join(cat_list)

        # 2. Try personal_finance_category.primary
        if not category:
            pfc = tx.get("personal_finance_category", {})
            category = (
                pfc.get("primary")
                or pfc.get("detailed")
                or None
            )

        # 3. Fallback to Uncategorized
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


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------


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

@app.route("/forgot_password.html")
def forgot_password_page():
    return render_template("forgot_password.html")


@app.route("/settings.html")
@login_required
def settings():
    return render_template("settings.html")


@app.route("/transaction-details.html")
@login_required
def transactiondetails():
    return render_template("transaction-details.html")


@app.route("/edit-profile.html")
@login_required
def edit_profile():
    return render_template("edit_profile.html")


@app.route("/budget-limit")
@login_required
def budget_limit():
    return render_template("budget_limit.html")


@app.route("/ai-insights")
@login_required
def ai_insights():
    return render_template("ai_insights.html")


@app.route("/entry")
@login_required
def entry_page():
    return render_template("entry.html")

# ---------------------------------------------------------------------------
# BANK / PLAID APIs
# ---------------------------------------------------------------------------


@app.route("/api/bank/connect-sandbox", methods=["POST"])
@login_required
def api_bank_connect_sandbox():
    """
    Attach a Plaid SANDBOX account to the logged-in user.

    - Creates a sandbox access_token (fake bank)
    - Fetches current balance + recent transactions
    - Stores everything in bank_account_connected collection
    """
    user_id = session.get("user_id")
    user = users_col.find_one({"_id": ObjectId(user_id)})
    if not user:
        return jsonify({"ok": False, "message": "User not found."}), 404

    email = (user.get("email") or "").strip().lower()
    if not email:
        return jsonify({"ok": False, "message": "User email missing."}), 400

    try:
        sandbox_creds = create_sandbox_access_token()
        access_token = sandbox_creds["access_token"]
        item_id = sandbox_creds["item_id"]

        balances_raw = get_current_balances(access_token)
        tx_raw = get_recent_transactions(access_token, days=30, count=100)

        total_balance = _compute_total_balance(balances_raw)
        recent_tx = _simplify_transactions(tx_raw)

        doc = {
            "user_id": user_id,
            "email": email,
            "access_token": access_token,  # in real prod, encrypt this
            "item_id": item_id,
            "current_balance": float(total_balance),
            "recent_transactions": recent_tx,
            "updated_at": datetime.utcnow(),
        }

        bank_accounts_col.update_one(
            {"user_id": user_id},
            {"$set": doc},
            upsert=True,
        )

        return jsonify({
            "ok": True,
            "connected": True,
            "current_balance": doc["current_balance"],
            "recent_transactions": doc["recent_transactions"],
        }), 200

    except Exception as e:
        print("[bank/connect-sandbox] ERROR:", e)
        return jsonify({"ok": False, "message": "Failed to connect sandbox bank."}), 500


@app.route("/api/bank/status", methods=["GET"])
@login_required
def api_bank_status():
    """
    Returns whether the user has a bank connected.
    If connected, refreshes balances + recent transactions from Plaid sandbox.
    """
    user_id = session.get("user_id")
    doc = bank_accounts_col.find_one({"user_id": user_id})

    if not doc:
        return jsonify({"ok": True, "connected": False}), 200

    access_token = doc.get("access_token")
    if not access_token:
        bank_accounts_col.delete_one({"_id": doc["_id"]})
        return jsonify({"ok": True, "connected": False}), 200

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
        }), 200

    except Exception as e:
        print("[bank/status] ERROR:", e)
        return jsonify({
            "ok": True,
            "connected": True,
            "current_balance": doc.get("current_balance"),
            "recent_transactions": doc.get("recent_transactions", []),
            "warning": "Failed to refresh from Plaid; returned cached data.",
        }), 200


@app.route("/api/bank/disconnect", methods=["POST"])
@login_required
def api_bank_disconnect():
    """
    Remove the sandbox bank from this user.
    (For sandbox we just delete the record.)
    """
    user_id = session.get("user_id")
    bank_accounts_col.delete_one({"user_id": user_id})
    return jsonify({"ok": True, "connected": False, "message": "Bank disconnected."}), 200


# ---------------------------------------------------------------------------
# API: Register
# ---------------------------------------------------------------------------

@app.route("/api/register", methods=["POST"])
def api_register():
    data = request.get_json(silent=True) or {}

    full_name = (data.get("fullName") or data.get("fullname") or "").strip()
    username = (data.get("username") or "").strip().lower()
    email = (data.get("email") or "").strip().lower()
    password = (data.get("password") or "")
    role = (data.get("role") or "").strip()

    if not full_name or " " not in full_name:
        return jsonify({"ok": False, "message": "Enter your full name."}), 400
    if not username or len(username) < 3:
        return jsonify({"ok": False, "message": "Username must be at least 3 characters."}), 400
    if not email:
        return jsonify({"ok": False, "message": "Valid email is required."}), 400
    if len(password) < 8:
        return jsonify({"ok": False, "message": "Password must be at least 8 characters."}), 400

    existing = users_col.find_one({"$or": [{"email": email}, {"username": username}]})
    if existing:
        return jsonify({"ok": False, "message": "Email or username already registered."}), 409

    pw_hash = hash_password(password)
    user_doc = {
        "fullName": full_name,
        "username": username,
        "email": email,
        "password_hash": pw_hash,
        "role": role or None,
        "totp_secret": None,
        "twofa_enabled": False,
        "created_at": datetime.utcnow(),
    }
    result = users_col.insert_one(user_doc)

    session.clear()
    session["user_id"] = str(result.inserted_id)
    session["identifier"] = email or username

    return jsonify({
        "ok": True,
        "message": "Account created successfully.",
        "redirect": "/dashboard.html"
    }), 201

# ---------------------------------------------------------------------------
# API: Login (Step 1) + Verify 2FA (Step 2)
# ---------------------------------------------------------------------------


@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.get_json(silent=True) or {}
    identifier = (data.get("identifier") or "").strip()
    password = (data.get("password") or "")
    invalid_msg = "Invalid credentials."

    raw_next = data.get("next") or request.args.get("next") or ""
    next_url = raw_next if _is_safe_url(raw_next) else ""

    user = find_user_by_identifier(identifier)
    if not user or not verify_password(password, user.get("password_hash", "")):
        return jsonify({"ok": False, "message": invalid_msg}), 401

    if user.get("twofa_enabled") and user.get("totp_secret"):
        session.clear()
        session["pending_2fa_user_id"] = str(user["_id"])
        session["pending_next"] = next_url
        return jsonify({
            "ok": True,
            "require_2fa": True,
            "message": "Password accepted. Proceeding to verification…"
        }), 200

    session.clear()
    session["user_id"] = str(user["_id"])
    session["identifier"] = user.get("email") or user.get("username")
    redirect_to = next_url or "/dashboard.html"

    return jsonify({"ok": True, "require_2fa": False, "redirect": redirect_to}), 200


@app.route("/api/verify-2fa", methods=["POST"])
def api_verify_2fa():
    user_id = session.get("pending_2fa_user_id")
    if not user_id:
        return jsonify({"ok": False, "message": "No verification in progress."}), 400

    user = users_col.find_one({"_id": ObjectId(user_id)})
    if not user or not user.get("twofa_enabled") or not user.get("totp_secret"):
        session.pop("pending_2fa_user_id", None)
        session.pop("pending_next", None)
        return jsonify({"ok": False, "message": "2FA not configured."}), 400

    data = request.get_json(silent=True) or {}
    code = (data.get("code") or "").strip()
    if not (code.isdigit() and len(code) == 6):
        return jsonify({"ok": False, "message": "Enter the 6-digit code."}), 400

    totp = pyotp.TOTP(user["totp_secret"])
    if not totp.verify(code, valid_window=1):
        return jsonify({"ok": False, "message": "Invalid or expired code."}), 401

    session["user_id"] = str(user["_id"])
    session["identifier"] = user.get("email") or user.get("username")
    next_url = session.pop("pending_next", "")
    session.pop("pending_2fa_user_id", None)
    redirect_to = next_url if _is_safe_url(next_url) else "/dashboard.html"

    return jsonify({"ok": True, "message": "Two-factor verified. Logged in.", "redirect": redirect_to}), 200

# ---------------------------------------------------------------------------
# API: Enable / Disable 2FA
# ---------------------------------------------------------------------------


@app.route("/api/2fa-status", methods=["GET"])
@login_required
def get_2fa_status():
    user_id = session.get("user_id")
    user = users_col.find_one({"_id": ObjectId(user_id)})

    if not user:
        return jsonify({"ok": False, "message": "User not found."}), 404

    twofa_enabled = bool(user.get("twofa_enabled") and user.get("totp_secret"))
    qr_b64 = None
    secret = None

    if twofa_enabled:
        otp_uri = pyotp.TOTP(user["totp_secret"]).provisioning_uri(
            name=user["email"], issuer_name="BudgetMind AI"
        )
        qr_img = qrcode.make(otp_uri)
        buf = io.BytesIO()
        qr_img.save(buf, format="PNG")
        qr_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
        secret = user["totp_secret"]

    return jsonify({
        "ok": True,
        "enabled": twofa_enabled,
        "qrCode": f"data:image/png;base64,{qr_b64}" if qr_b64 else None,
        "secret": secret
    }), 200


@app.route("/api/setup-2fa", methods=["POST"])
@login_required
def setup_2fa():
    user_id = session.get("user_id")
    user = users_col.find_one({"_id": ObjectId(user_id)})
    if not user:
        return jsonify({"ok": False, "message": "User not found."}), 404

    if user.get("twofa_enabled") and user.get("totp_secret"):
        return jsonify({"ok": True, "message": "2FA already active."}), 200

    secret = pyotp.random_base32()
    users_col.update_one(
        {"_id": ObjectId(user_id)},
        {"$set": {"twofa_enabled": True, "totp_secret": secret}}
    )

    otp_uri = pyotp.TOTP(secret).provisioning_uri(name=user["email"], issuer_name="BudgetMind AI")
    qr_img = qrcode.make(otp_uri)
    buf = io.BytesIO()
    qr_img.save(buf, format="PNG")
    qr_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

    return jsonify({
        "ok": True,
        "message": "2FA enabled. Scan this QR code in Google Authenticator.",
        "qrCode": f"data:image/png;base64,{qr_b64}",
        "secret": secret
    }), 200


@app.route("/api/disable-2fa", methods=["POST"])
@login_required
def disable_2fa():
    user_id = session.get("user_id")
    users_col.update_one(
        {"_id": ObjectId(user_id)},
        {"$set": {"twofa_enabled": False, "totp_secret": None}}
    )
    return jsonify({"ok": True, "message": "Two-factor authentication disabled."}), 200

# ---------------------------------------------------------------------------
# API: Get / Update Profile Picture & Profile
# ---------------------------------------------------------------------------


@app.route("/api/profile-picture/<user_id>")
@login_required
def get_profile_picture(user_id):
    pic = profile_pics_col.find_one({"user_id": user_id})
    if not pic:
        return jsonify({"ok": False, "message": "No profile picture found."}), 404

    return jsonify({
        "ok": True,
        "image": f"data:image/png;base64,{pic['image']}"
    })


@app.route("/api/update-profile", methods=["POST"])
@login_required
def update_profile():
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
        encoded_img = base64.b64encode(image_bytes).decode("utf-8")

        profile_pics_col.delete_many({"user_id": user_id})

        profile_pics_col.insert_one({
            "user_id": user_id,
            "username": update_fields.get("username") or data.get("username"),
            "image": encoded_img,
            "updated_at": datetime.utcnow()
        })

        update_fields["profilePic"] = f"/api/profile-picture/{user_id}"

    if not update_fields:
        return jsonify({"ok": False, "message": "No changes detected."}), 400

    users_col.update_one({"_id": ObjectId(user_id)}, {"$set": update_fields})

    updated_user = users_col.find_one({"_id": ObjectId(user_id)}, {"password_hash": 0})
    if updated_user and "_id" in updated_user:
        updated_user["_id"] = str(updated_user["_id"])

    return jsonify({"ok": True, "message": "Profile updated successfully.", "user": updated_user}), 200

# ---------------------------------------------------------------------------
# Forgot Password
# ---------------------------------------------------------------------------


@app.route("/api/forgot_password", methods=["POST"])
def forgot_password():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    new_password = (data.get("newPassword") or "").strip()

    if not email or not new_password:
        return jsonify({"ok": False, "message": "Email and new password required."}), 400

    user = users_col.find_one({"email": email})
    if not user:
        return jsonify({"ok": False, "message": "No account found with that email."}), 404

    pw_hash = hash_password(new_password)
    users_col.update_one({"_id": user["_id"]}, {"$set": {"password_hash": pw_hash}})
    print(f"🔐 Password reset for user: {email}")

    return jsonify({"ok": True, "message": "Password updated successfully."}), 200

# ---------------------------------------------------------------------------
# Summary API: Income vs Expense (Plaid first; fallback to entries)
# ---------------------------------------------------------------------------


@app.route("/api/summary")
@login_required
def api_summary():
    user_id = session.get("user_id")

    # Try Plaid-based summary first
    bank_doc = bank_accounts_col.find_one({"user_id": user_id})
    if bank_doc and bank_doc.get("recent_transactions"):
        total_income = 0.0
        total_expense = 0.0
        category_totals: dict[str, float] = {}

        for tx in bank_doc["recent_transactions"]:
            amt = float(tx.get("amount", 0) or 0)
            signed = tx.get("signed_amount")

            if signed is None:
                # Re-derive if missing
                name = tx.get("name") or ""
                cat_str = tx.get("category")
                is_income = _classify_direction(name, cat_str)
                signed = amt if is_income else -amt

            if signed > 0:
                total_income += signed
            elif signed < 0:
                exp_val = abs(signed)
                total_expense += exp_val
                cat_name = tx.get("category") or "Other"
                category_totals[cat_name] = category_totals.get(cat_name, 0.0) + exp_val

        categories_list = [
            {"name": name, "total": total}
            for name, total in category_totals.items()
        ]
        categories_list.sort(key=lambda x: x["total"], reverse=True)

        return jsonify({
            "income": float(total_income),
            "expense": float(total_expense),
            "categories": categories_list,
        }), 200

    # Fallback: use manual entries if no bank transactions
    entries = list(entries_col.find({"user_id": user_id}))
    total_income = sum(
        float(e.get("amount", 0))
        for e in entries
        if str(e.get("type", "")).lower() == "income"
    )
    total_expense = sum(
        float(e.get("amount", 0))
        for e in entries
        if str(e.get("type", "")).lower() == "expense"
    )

    category_totals = {}
    for e in entries:
        if str(e.get("type", "")).lower() == "expense":
            cat = str(e.get("category", "Other")).capitalize()
            category_totals[cat] = category_totals.get(cat, 0.0) + float(e.get("amount", 0))

    sorted_categories = sorted(category_totals.items(), key=lambda x: x[1], reverse=True)
    return jsonify({
        "income": float(total_income),
        "expense": float(total_expense),
        "categories": [{"name": c, "total": t} for c, t in sorted_categories]
    }), 200

# ---------------------------------------------------------------------------
# AI Chat (simple rules)
# ---------------------------------------------------------------------------


@app.route("/api/ai-chat", methods=["POST"])
@login_required
def api_ai_chat():
    data = request.get_json(silent=True) or {}
    user_msg = (data.get("message") or "").strip().lower()
    if not user_msg:
        return jsonify({"reply": "Please type something to chat!"})

    if "save" in user_msg:
        reply = "💰 Try putting aside 10% of your income each month."
    elif "budget" in user_msg:
        reply = "📊 A balanced budget splits expenses 50/30/20."
    elif "spend" in user_msg or "expenses" in user_msg:
        reply = "💸 Review your top spending categories — dining and subscriptions are common culprits."
    elif "income" in user_msg:
        reply = "💵 Consider diversifying your income sources."
    elif "hello" in user_msg or "hi" in user_msg:
        reply = "👋 Hey there! I'm your BudgetMind AI assistant."
    else:
        reply = "🤖 I'm still learning, but I can help with budgeting, saving, or spending insights!"

    return jsonify({"reply": reply})

# ---------------------------------------------------------------------------
# Manual Entry API (still used for budget limit features)
# ---------------------------------------------------------------------------


@app.route("/entry", methods=["POST"])
@login_required
def add_entry():
    user_id = session.get("user_id")

    type_ = request.form.get("type")
    category = request.form.get("category")
    amount = request.form.get("amount")

    if not type_ or not category or not amount:
        return jsonify({"ok": False, "message": "Missing fields."}), 400

    try:
        amount = float(amount)
    except:
        return jsonify({"ok": False, "message": "Invalid amount."}), 400

    entry_doc = {
        "user_id": user_id,
        "type": type_,
        "category": category.strip().title(),
        "amount": amount,
        "created_at": datetime.utcnow(),
    }

    entries_col.insert_one(entry_doc)

    if str(type_).lower() == "expense":
        recalc_spending_flag_for_user(user_id)

    return jsonify({"ok": True, "message": "Entry added successfully!"}), 201

# ---------------------------------------------------------------------------
# User Profile API
# ---------------------------------------------------------------------------


@app.route("/api/user-profile")
@login_required
def api_user_profile():
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"ok": False, "message": "Not logged in"}), 401

    user = users_col.find_one({"_id": ObjectId(user_id)}, {"password_hash": 0})
    if not user:
        return jsonify({"ok": False, "message": "User not found"}), 404

    user["_id"] = str(user["_id"])
    return jsonify({"ok": True, "user": user}), 200

# ---------------------------------------------------------------------------
# Transactions API (for transaction-details page)
# ---------------------------------------------------------------------------


@app.route("/api/transactions", methods=["GET"])
@login_required
def api_transactions():
    """
    Return up to ?limit=50 recent Plaid transactions for the logged-in user.
    """
    user_id = session.get("user_id")
    doc = bank_accounts_col.find_one({"user_id": user_id})
    if not doc or not doc.get("recent_transactions"):
        return jsonify({"ok": True, "transactions": []}), 200

    tx_list = doc["recent_transactions"]

    # Sort newest -> oldest by date string (YYYY-MM-DD)
    tx_list_sorted = sorted(
        tx_list,
        key=lambda tx: tx.get("date") or "",
        reverse=True
    )

    try:
        limit = int(request.args.get("limit", 50))
    except ValueError:
        limit = 50

    return jsonify({
        "ok": True,
        "transactions": tx_list_sorted[:limit],
    }), 200


@app.route("/api/transactions/<tx_id>", methods=["GET"])
@login_required
def api_transaction_detail(tx_id):
    """
    Return a single transaction by Plaid transaction_id.
    """
    user_id = session.get("user_id")
    doc = bank_accounts_col.find_one({"user_id": user_id})
    if not doc or not doc.get("recent_transactions"):
        return jsonify({"ok": False, "message": "No transactions found."}), 404

    for tx in doc["recent_transactions"]:
        if tx.get("transaction_id") == tx_id:
            return jsonify({"ok": True, "transaction": tx}), 200

    return jsonify({"ok": False, "message": "Transaction not found."}), 404


#NOTES#

from bson.objectid import ObjectId
from datetime import datetime

@app.route("/notes", methods=["GET"])
@login_required
def notes_page():
    """Show all notes for logged-in user"""
    user_id = session.get("user_id")
    user_notes = list(notes_col.find({"user_id": user_id}).sort("created_at", -1))
    return render_template("notes.html", notes=user_notes)

@app.route("/notes/add", methods=["POST"])
@login_required
def add_note():
    """Add a new note"""
    user_id = session.get("user_id")
    title = request.form.get("title", "").strip()
    content = request.form.get("content", "").strip()

    if not title or not content:
        return redirect("/notes")

    note_doc = {
        "user_id": user_id,
        "title": title,
        "content": content,
        "created_at": datetime.utcnow(),
    }

    notes_col.insert_one(note_doc)
    return redirect("/notes")

@app.route("/notes/delete/<note_id>", methods=["POST"])
@login_required
def delete_note(note_id):
    """Delete an existing note"""
    notes_col.delete_one({"_id": ObjectId(note_id)})
    return redirect("/notes")



def assign_category(name: str) -> str:
    if not name:
        return "Other"
    
    n = name.lower()

    # Dining
    if "starbucks" in n or "mcdonald" in n or "pizza" in n or "coffee" in n:
        return "Dining"

    # Transport
    if "uber" in n or "lyft" in n or "taxi" in n or "bus" in n:
        return "Transport"

    # Travel
    if "airlines" in n or "hotel" in n or "airbnb" in n:
        return "Travel"

    # Shopping
    if "amazon" in n or "walmart" in n or "target" in n or "sparkfun" in n:
        return "Shopping"

    # Fitness
    if "gym" in n or "fitness" in n or "climbing" in n:
        return "Fitness"

    # Income (ignore in pie)
    if "deposit" in n or "payroll" in n or "credit" in n:
        return "Income"

    # Bills
    if "payment" in n or "bill" in n:
        return "Bills"

    return "Other"



@app.get("/api/category-breakdown")
@login_required
def api_category_breakdown():
    user_id = session.get("user_id")

    bank_doc = bank_accounts_col.find_one({"user_id": user_id})
    if not bank_doc or not bank_doc.get("access_token"):
        return jsonify([]), 200

    access_token = bank_doc["access_token"]
    tx_response = get_recent_transactions(access_token, days=30)
    transactions = tx_response.get("transactions", [])

    summary = {}

    for tx in transactions:
        name = tx.get("name", "")
        amount = float(tx.get("amount", 0))

        # classify category
        cat = assign_category(name)

        # Only expenses go in pie chart
        if amount > 0:  
            summary[cat] = summary.get(cat, 0) + amount

    breakdown = [
        {"category": cat, "total": round(total, 2)}
        for cat, total in summary.items()
    ]

    breakdown.sort(key=lambda x: x["total"], reverse=True)

    return jsonify(breakdown)



# ---------------------------------------------------------------------------
# Logout & Run
# ---------------------------------------------------------------------------


@app.route("/logout", methods=["GET", "POST"])
def logout():
    session.clear()
    if request.method == "POST":
        return jsonify({"ok": True, "redirect": "/"})
    return redirect("/")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)
