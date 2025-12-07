import pytest
from app import app, db
from bson import ObjectId

@pytest.fixture
def client():
    app.testing = True
    test_client = app.test_client()

  
    with test_client.session_transaction() as session:
        session["user_id"] = "6777aaaaaaaaaaaaaaaaaaaaaa"  
        session["role"] = "Average User"

    return test_client



def test_create_goal(client):
    payload = {
        "name": "Test Goal",
        "target_amount": 5000,
        "current_amount": 100,
        "deadline": "2025-12-31"
    }

    response = client.post("/api/goals", json=payload)
    assert response.status_code in [200, 201]

    data = response.get_json()
    assert "id" in data

    
    db.goals.delete_one({"_id": ObjectId(data["id"])})



def test_get_goals(client):
    
    fake_goal = {
        "_id": ObjectId(),
        "user_id": "6777aaaaaaaaaaaaaaaaaaaaaa",
        "name": "Temp Goal",
        "target_amount": 1000,
        "current_amount": 20,
        "deadline": "2025-01-01"
    }
    db.goals.insert_one(fake_goal)

    response = client.get("/api/goals")
    assert response.status_code == 200

    data = response.get_json()
    assert isinstance(data, list)

    
    db.goals.delete_one({"_id": fake_goal["_id"]})



def test_update_goal(client):
    goal_id = ObjectId()
    db.goals.insert_one({
        "_id": goal_id,
        "user_id": "6777aaaaaaaaaaaaaaaaaaaaaa",
        "name": "Before Update"
    })

    response = client.put(f"/api/goals/{goal_id}", json={"name": "Updated Name"})
    assert response.status_code == 200

    
    updated = db.goals.find_one({"_id": goal_id})
    assert updated["name"] == "Updated Name"

  
    db.goals.delete_one({"_id": goal_id})



def test_delete_goal(client):
    
    goal_id = ObjectId()
    db.goals.insert_one({
        "_id": goal_id,
        "user_id": "6777aaaaaaaaaaaaaaaaaaaaaa",
        "name": "Delete Me"
    })

    response = client.delete(f"/api/goals/{goal_id}")
    assert response.status_code == 200

   
    deleted = db.goals.find_one({"_id": goal_id})
    assert deleted is None



def test_select_advisor(client):
  
    user_id = ObjectId()
    db.users.insert_one({
        "_id": user_id,
        "email": "avg@test.com",
        "password_hash": "x",
        "role": "Average User",
        "fullName": "Test User"
    })

    db.financially_vulnerable_users.insert_one({
        "user_id": str(user_id),
        "risk_level": "low"
    })

    with client.session_transaction() as session:
        session["user_id"] = str(user_id)
        session["role"] = "Average User"

    advisor_id = ObjectId()
    db.users.insert_one({
        "_id": advisor_id,
        "email": "advisor@test.com",
        "role": "Financial Advisor",
        "fullName": "Advisor Person"
    })

    payload = {"advisor_id": str(advisor_id)}

    response = client.post("/api/user/select_advisor", json=payload)

    if response.status_code not in [200, 201]:
        print("DEBUG:", response.get_json())

    assert response.status_code in [200, 201]

    data = response.get_json()
    assert data["ok"] is True

    # Cleanup
    db.users.delete_one({"_id": advisor_id})
    db.users.delete_one({"_id": user_id})
    db.clients.delete_many({"advisor_id": advisor_id})
    db.notifications.delete_many({"user_id": advisor_id})
    db.financially_vulnerable_users.delete_many({"user_id": str(user_id)})
