import os
import sys
from fastapi.testclient import TestClient
from dotenv import load_dotenv

load_dotenv()

# Force local sqlite for test
os.environ["DATABASE_URL"] = "sqlite:///./agrinex.db"

from app.main import app
from app.database import Base, engine, get_db
from app import models, auth_utils
from sync_db import sync_db

client = TestClient(app)

def test_social_platform_endpoints():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = next(get_db())

    # Ensure test users exist
    u1 = db.query(models.User).filter(models.User.email == "test_farmer1@agrinex.io").first()
    if not u1:
        u1 = models.User(
            email="test_farmer1@agrinex.io",
            full_name="Ramesh Kumar",
            username="ramesh_farm",
            hashed_password="$2b$12$dummyhashforrameshkumaragrinextest",
            village="Punjab Farm Hub",
            crop_specialization="Wheat & Mustard"
        )
        db.add(u1)
    
    u2 = db.query(models.User).filter(models.User.email == "test_farmer2@agrinex.io").first()
    if not u2:
        u2 = models.User(
            email="test_farmer2@agrinex.io",
            full_name="Suresh Patel",
            username="suresh_patel",
            hashed_password="$2b$12$dummyhashforsureshpatelagrinextest",
            village="Gujarat Agritech",
            crop_specialization="Cotton & Groundnut"
        )
        db.add(u2)
    db.commit()
    db.refresh(u1)
    db.refresh(u2)

    # Auth token for u1
    token1 = auth_utils.create_access_token(data={"sub": u1.email})
    headers1 = {"Authorization": f"Bearer {token1}"}

    # 1. Get User Profile
    res = client.get(f"/api/users/{u2.id}", headers=headers1)
    assert res.status_code == 200, res.text
    profile_data = res.json()
    assert profile_data["id"] == u2.id
    assert "followers_count" in profile_data
    assert "isFollowing" in profile_data

    # 2. Search Users
    res = client.get("/api/users/search?q=Suresh", headers=headers1)
    assert res.status_code == 200, res.text
    search_data = res.json()
    assert len(search_data) >= 1
    assert search_data[0]["id"] == u2.id

    # 3. Follow User (via /social/follow endpoint alias)
    res = client.post(f"/social/follow/{u2.id}", headers=headers1)
    assert res.status_code == 200, res.text
    follow_data = res.json()
    assert follow_data["isFollowing"] is True
    assert follow_data["followersCount"] >= 1

    # 4. Prevent Following Self
    res = client.post(f"/social/follow/{u1.id}", headers=headers1)
    assert res.status_code == 400

    # 5. Suggested Farmers
    res = client.get("/api/users/suggested", headers=headers1)
    assert res.status_code == 200

    # 6. User Followers & Following
    res = client.get(f"/api/users/{u2.id}/followers", headers=headers1)
    assert res.status_code == 200
    assert any(f["id"] == u1.id for f in res.json())

    res = client.get(f"/api/users/{u1.id}/following", headers=headers1)
    assert res.status_code == 200
    assert any(f["id"] == u2.id for f in res.json())

    # 7. Edit Profile (PATCH /users/me)
    res = client.patch("/users/me", json={"bio": "Master Organic Farmer", "website": "https://rameshfarms.org"}, headers=headers1)
    assert res.status_code == 200, res.text
    assert res.json()["bio"] == "Master Organic Farmer"
    assert res.json()["website"] == "https://rameshfarms.org"

    # 8. User Posts Grid Endpoint
    res = client.get(f"/posts/user/{u1.id}", headers=headers1)
    assert res.status_code == 200, res.text

    # 9. Unfollow User (via /social/follow endpoint alias)
    res = client.delete(f"/social/follow/{u2.id}", headers=headers1)
    assert res.status_code == 200
    unfollow_data = res.json()
    assert unfollow_data["isFollowing"] is False

    print("ALL SOCIAL PLATFORM BACKEND TESTS PASSED!")

if __name__ == "__main__":
    test_social_platform_endpoints()
