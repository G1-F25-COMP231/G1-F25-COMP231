# tests/test_app.py

import pytest
from app import app, db, users_col, clients_col
from bson import ObjectId
from app import hash_password



# --------------------------------------------------------
# FIXED CLIENT FIXTURE — ALWAYS USES VALID OBJECTID
# --------------------------------------------------------
@pytest.fixture
def client():
    app.testing = True
    test_client = app.test_client()

    with test_client.session_transaction() as session:
        valid_oid = ObjectId()                 # valid ObjectId
        session["user_id"] = str(valid_oid)    # store as string
        session["role"] = "Average User"

    return test_client


# --------------------------------------------------------
# TEST 1 — AVISOR NOTIFICATION
# --------------------------------------------------------
def test_advisor_notification(client):
    from app import users_col, notifications_col

    # Create fake user and advisor
    user_id = ObjectId()
    advisor_id = ObjectId()

    users_col.insert_one({
        "_id": user_id,
        "fullName": "Test User",
        "email": "testuser@x.com",
        "role": "Average User"
    })

    users_col.insert_one({
        "_id": advisor_id,
        "fullName": "Advisor A",
        "email": "advisor@x.com",
        "role": "Financial Advisor"
    })

    # Force session user to real user
    with client.session_transaction() as s:
        s["user_id"] = str(user_id)
        s["role"] = "Average User"

    res = client.post("/api/user/select_advisor", json={
        "advisor_id": str(advisor_id)
    })

    assert res.status_code in (200, 201)
    data = res.get_json()
    assert data["ok"] is True

    # Check notification exists for advisor
    notif = notifications_col.find_one({"user_id": advisor_id})
    assert notif is not None
    assert notif["type"] == "new_client"
    assert notif["read"] is False

    # Cleanup
    users_col.delete_one({"_id": user_id})
    users_col.delete_one({"_id": advisor_id})
    notifications_col.delete_many({"user_id": advisor_id})



# --------------------------------------------------------
# TEST 2 — REGISTRATION
# --------------------------------------------------------
def test_registration(client):
    payload = {
        "fullName": "John Doe",
        "username": "johnny",
        "email": "john@example.com",
        "password": "mypassword123",
        "role": "Average User"
    }

    res = client.post("/api/register", json=payload)
    assert res.status_code in (200, 201)
    data = res.get_json()
    assert data["ok"] is True

    users_col.delete_one({"email": "john@example.com"})


# --------------------------------------------------------
# TEST 3 — GET TRANSACTIONS
# --------------------------------------------------------
def test_get_transactions(client):
    # Get actual logged-in user from session
    with client.session_transaction() as s:
        logged_user_id = s["user_id"]

    # Insert fake transactions
    from app import bank_accounts_col

    bank_accounts_col.insert_one({
    "_id": ObjectId(),
    "user_id": logged_user_id,
    "recent_transactions": [
        {"transaction_id": "tx1", "name": "Starbucks", "amount": 8, "date": "2025-01-01"},
        {"transaction_id": "tx2", "name": "Uber", "amount": 21, "date": "2025-01-02"}
    ]
})


    res = client.get("/api/transactions")
    assert res.status_code == 200
    data = res.get_json()
    assert data["ok"] is True
    assert len(data["transactions"]) == 2


# --------------------------------------------------------
# TEST 4 — CREATE GOAL
# --------------------------------------------------------
def test_create_goal(client):
    payload = {
        "name": "Save for Car",
        "target_amount": 10000,
        "current_amount": 500,
        "deadline": "2025-12-31"
    }

    res = client.post("/api/goals", json=payload)
    assert res.status_code in (200, 201)
    data = res.get_json()
    assert "id" in data

    db.goals.delete_one({"_id": ObjectId(data["id"])})


# --------------------------------------------------------
# TEST 5 — SELECT ADVISOR
# --------------------------------------------------------
def test_select_advisor(client):
    # Fetch the valid logged-in user ID from the session
    with client.session_transaction() as s:
        logged_user_id = s["user_id"]

    logged_user_oid = ObjectId(logged_user_id)

    # Insert logged-in user into DB (required for notifications)
    users_col.insert_one({
        "_id": logged_user_oid,
        "fullName": "Test User",
        "email": "user@test.com",
        "role": "Average User"
    })

    # Insert advisor
    advisor_oid = ObjectId()
    users_col.insert_one({
        "_id": advisor_oid,
        "fullName": "Advisor A",
        "email": "advisor@test.com",
        "role": "Financial Advisor"
    })

    # Make request
    res = client.post("/api/user/select_advisor", json={
        "advisor_id": str(advisor_oid)
    })

    assert res.status_code in (200, 201)
    data = res.get_json()
    assert data["ok"] is True

    # Cleanup
    users_col.delete_one({"_id": logged_user_oid})
    users_col.delete_one({"_id": advisor_oid})
    clients_col.delete_many({"advisor_id": advisor_oid})
