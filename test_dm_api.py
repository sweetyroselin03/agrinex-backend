import os
import sys
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

TEST_DB_FILE = "./test_dm.db"
if os.path.exists(TEST_DB_FILE):
    try:
        os.remove(TEST_DB_FILE)
    except Exception:
        pass

os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB_FILE}"

from app.database import Base, get_db
from app.main import app, get_current_user, get_optional_current_user
from app import models


engine = create_engine(f"sqlite:///{TEST_DB_FILE}", connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base.metadata.drop_all(bind=engine)
Base.metadata.create_all(bind=engine)

def override_get_db():
    try:
        db = TestingSessionLocal()
        yield db
    finally:
        db.close()

app.dependency_overrides[get_db] = override_get_db

# Create test users
db = TestingSessionLocal()
u1 = models.User(email="farmer1@agrinex.io", full_name="Farmer One", username="farmer1")
u2 = models.User(email="farmer2@agrinex.io", full_name="Farmer Two", username="farmer2")
u3 = models.User(email="farmer3@agrinex.io", full_name="Farmer Three", username="farmer3")
db.add_all([u1, u2, u3])
db.commit()
db.refresh(u1)
db.refresh(u2)
db.refresh(u3)
db.close()

def get_user_1():
    db = TestingSessionLocal()
    return db.query(models.User).filter(models.User.id == u1.id).first()

def get_user_2():
    db = TestingSessionLocal()
    return db.query(models.User).filter(models.User.id == u2.id).first()

client = TestClient(app)

def test_start_conversation():
    app.dependency_overrides[get_current_user] = get_user_1
    res = client.post("/messages/start", json={"target_user_id": u2.id})
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["type"] == "direct"
    assert data["other_participant"]["user_id"] == u2.id
# Remove checkmark prints inside functions

def test_send_and_get_messages():
    app.dependency_overrides[get_current_user] = get_user_1
    # Send message from user 1 to user 2
    res = client.post("/messages/send", json={
        "recipient_id": u2.id,
        "content": "Hello Farmer Two! Welcome to AgriNex DMs.",
        "attachments": ["https://agrinex.io/crop.jpg"]
    })
    assert res.status_code == 200, res.text
    msg = res.json()
    assert msg["content"] == "Hello Farmer Two! Welcome to AgriNex DMs."
    assert len(msg["attachments"]) == 1
    conv_id = msg["conversation_id"]

    # Get conversation messages as user 2
    app.dependency_overrides[get_current_user] = get_user_2
    res2 = client.get(f"/messages/{conv_id}")
    assert res2.status_code == 200, res2.text
    messages = res2.json()
    assert len(messages) == 1
    assert messages[0]["sender_id"] == u1.id

def test_mark_read_and_reactions():
    app.dependency_overrides[get_current_user] = get_user_1
    res_start = client.post("/messages/start", json={"target_user_id": u2.id})
    conv_id = res_start.json()["id"]

    # Send msg from U1
    res_msg = client.post("/messages/send", json={"conversation_id": conv_id, "content": "Test reaction"})
    msg_id = res_msg.json()["id"]

    # Reaction from U2
    app.dependency_overrides[get_current_user] = get_user_2
    res_react = client.post(f"/messages/reaction?msg_id={msg_id}", json={"emoji": "❤️"})
    assert res_react.status_code == 200, res_react.text
    reactions = res_react.json()["reactions"]
    assert len(reactions) == 1
    assert reactions[0]["emoji"] == "❤️"

    # Read receipt from U2
    res_read = client.post(f"/messages/read?conv_id={conv_id}")
    assert res_read.status_code == 200, res_read.text

def test_edit_and_delete_message():
    app.dependency_overrides[get_current_user] = get_user_1
    res_start = client.post("/messages/start", json={"target_user_id": u2.id})
    conv_id = res_start.json()["id"]

    # Send msg
    res_msg = client.post("/messages/send", json={"conversation_id": conv_id, "content": "Original text"})
    msg_id = res_msg.json()["id"]

    # Edit msg
    res_edit = client.patch(f"/messages/edit?msg_id={msg_id}", json={"content": "Edited text"})
    assert res_edit.status_code == 200, res_edit.text
    assert res_edit.json()["content"] == "Edited text"
    assert res_edit.json()["is_edited"] == True

    # Delete for everyone
    res_del = client.delete(f"/messages/delete?msg_id={msg_id}&delete_type=everyone")
    assert res_del.status_code == 200, res_del.text

    res_check = client.get(f"/messages/{conv_id}")
    assert res_check.json()[-1]["content"] == "This message was deleted"

def test_pin_mute_archive_and_block():
    app.dependency_overrides[get_current_user] = get_user_1
    app.dependency_overrides[get_optional_current_user] = get_user_1
    res_start = client.post("/messages/start", json={"target_user_id": u2.id})
    conv_id = res_start.json()["id"]


    # Pin conversation
    res_pin = client.post(f"/api/conversations/{conv_id}/pin")
    assert res_pin.status_code == 200
    assert res_pin.json()["is_pinned"] == True

    # Test block status endpoint
    res_status = client.get(f"/api/users/{u2.id}/block-status")
    assert res_status.status_code == 200
    assert res_status.json()["is_blocked"] == False

    # Block user 2
    res_block = client.post(f"/api/users/{u2.id}/block")
    assert res_block.status_code == 200
    assert res_block.json()["blocked"] == True

    # Check block status now
    res_status2 = client.get(f"/api/users/{u2.id}/block-status")
    assert res_status2.status_code == 200
    assert res_status2.json()["is_blocked"] == True
    assert res_status2.json()["blocked_by_me"] == True

    # Duplicate block should return 409
    res_dup = client.post(f"/api/users/{u2.id}/block")
    assert res_dup.status_code == 409

    # Try sending msg to blocked user 2 -> should fail 403
    res_fail = client.post("/messages/send", json={"recipient_id": u2.id, "content": "Hello?"})
    assert res_fail.status_code == 403, res_fail.text

    # Search users should exclude blocked user 2
    res_search = client.get("/api/users/search?q=farmer2")
    assert res_search.status_code == 200
    search_ids = [u["id"] for u in res_search.json()]
    assert u2.id not in search_ids

    # Unblock user 2
    res_unblock = client.delete(f"/api/users/{u2.id}/block")
    assert res_unblock.status_code == 200
    assert res_unblock.json()["blocked"] == False

if __name__ == "__main__":
    test_start_conversation()
    print("[OK] TEST PASSED: start_conversation")
    test_send_and_get_messages()
    print("[OK] TEST PASSED: send_and_get_messages")
    test_mark_read_and_reactions()
    print("[OK] TEST PASSED: mark_read_and_reactions")
    test_edit_and_delete_message()
    print("[OK] TEST PASSED: edit_and_delete_message")
    test_pin_mute_archive_and_block()
    print("[OK] TEST PASSED: pin_mute_archive_and_block")
    print("\n==============================================")
    print("ALL DM BACKEND TESTS PASSED SUCCESSFULLY!")
    print("==============================================")

