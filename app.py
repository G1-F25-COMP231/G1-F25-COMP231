import os
import io
import base64
import qrcode
from functools import wraps
from datetime import datetime
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
notes_col = db.get_collection("notes")




# ---------------------------------------------------------------------------
# Spending limits / flags
# ---------------------------------------------------------------------------

DEFAULT_SPENDING_LIMIT = 1000.0  # fallback if user doesn't have their own limit


def recalc_spending_flag_for_user(user_id: str):
    """
    Recalculate a user's total expense and update:
      - user.is_flagged (True/False)
      - user.notes (add 'Spending limit exceeded' once when over limit)
    Currently uses ALL-TIME expenses. You can change this to monthly if needed.
    """
    try:
        user_obj_id = ObjectId(user_id)
    except Exception:
        return  # invalid id, nothing to do

    user = users_col.find_one({"_id": user_obj_id})
    if not user:
        return

    # 1) Compute total expenses for this user (all time)
    total_expense = 0.0
    for e in entries_col.find({"user_id": user_id}):
        if str(e.get("type", "")).lower() == "expense":
            try:
                total_expense += float(e.get("amount", 0))
            except (TypeError, ValueError):
                continue

    # 2) Get this user's limit (or default)
    try:
        spending_limit = float(user.get("spending_limit", DEFAULT_SPENDING_LIMIT))
    except (TypeError, ValueError):
        spending_limit = DEFAULT_SPENDING_LIMIT

    is_over = total_expense > spending_limit

    # 3) Prepare updates
    updates = {"is_flagged": is_over}

    # 4) If over the limit, ensure we have a "Spending limit exceeded" note
    if is_over:
        note_text = "Spending limit exceeded"
        notes = user.get("notes", [])

        # notes are stored as list of {"message": ..., "created_at": ...}
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

    # If user has 2FA enabled
    if user.get("twofa_enabled") and user.get("totp_secret"):
        session.clear()
        session["pending_2fa_user_id"] = str(user["_id"])
        session["pending_next"] = next_url
        return jsonify({
            "ok": True,
            "require_2fa": True,
            "message": "Password accepted. Proceeding to verification…"
        }), 200

    # Otherwise log in directly
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
    """Return whether the logged-in user has 2FA enabled."""
    user_id = session.get("user_id")
    user = users_col.find_one({"_id": ObjectId(user_id)})

    if not user:
        return jsonify({"ok": False, "message": "User not found."}), 404

    twofa_enabled = bool(user.get("twofa_enabled") and user.get("totp_secret"))
    qr_b64 = None
    secret = None

    if twofa_enabled:
        # Regenerate QR code for display (so it always shows)
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
    """Generate and enable 2FA, returning a QR code."""
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
# API: Get Profile Picture (Base64)
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

# ---------------------------------------------------------------------------
# API: Update Profile, Forgot Password, Summary, AI Chat
# ---------------------------------------------------------------------------

@app.route("/api/update-profile", methods=["POST"])
@login_required
def update_profile():
    user_id = session.get("user_id")
    data = request.form.to_dict()
    file = request.files.get("profilePic")
    update_fields = {}

    # --- Text Field Updates ---
    if data.get("fullName"):
        update_fields["fullName"] = data["fullName"].strip()
    if data.get("username"):
        update_fields["username"] = data["username"].strip().lower()
    if data.get("email"):
        update_fields["email"] = data["email"].strip().lower()
    if data.get("newPassword"):
        update_fields["password_hash"] = hash_password(data["newPassword"])

    # --- Profile Picture Upload to MongoDB ---
    if file and file.filename != "":
        image_bytes = file.read()
        encoded_img = base64.b64encode(image_bytes).decode("utf-8")

        # Remove old profile picture
        profile_pics_col.delete_many({"user_id": user_id})

        # Insert new image
        profile_pics_col.insert_one({
            "user_id": user_id,
            "username": update_fields.get("username") or data.get("username"),
            "image": encoded_img,
            "updated_at": datetime.utcnow()
        })

        # Reference stored inside users collection
        update_fields["profilePic"] = f"/api/profile-picture/{user_id}"

    # --- No fields changed ---
    if not update_fields:
        return jsonify({"ok": False, "message": "No changes detected."}), 400

    # --- Update User ---
    users_col.update_one({"_id": ObjectId(user_id)}, {"$set": update_fields})

    updated_user = users_col.find_one({"_id": ObjectId(user_id)}, {"password_hash": 0})
    if updated_user and "_id" in updated_user:
        updated_user["_id"] = str(updated_user["_id"])

    return jsonify({"ok": True, "message": "Profile updated successfully.", "user": updated_user}), 200



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


@app.route("/api/summary")
@login_required
def api_summary():
    user_id = session.get("user_id")
    entries = list(entries_col.find({"user_id": user_id}))
    total_income = sum(e["amount"] for e in entries if e["type"].lower() == "income")
    total_expense = sum(e["amount"] for e in entries if e["type"].lower() == "expense")

    category_totals = {}
    for e in entries:
        if e["type"].lower() == "expense":
            cat = e["category"].capitalize()
            category_totals[cat] = category_totals.get(cat, 0) + e["amount"]

    sorted_categories = sorted(category_totals.items(), key=lambda x: x[1], reverse=True)
    return jsonify({
        "income": total_income,
        "expense": total_expense,
        "categories": [{"name": c, "total": t} for c, t in sorted_categories]
    })


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


