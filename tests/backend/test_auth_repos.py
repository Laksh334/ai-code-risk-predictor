"""Backend: accounts, security, repositories, data isolation between users."""

from tests.conftest import make_user


def test_register_login_me(client):
    r = client.post("/api/auth/register", json={"email": "New@Example.com", "password": "testpass123"})
    assert r.status_code == 201 and r.json()["email"] == "new@example.com" and "hashed_password" not in r.json()
    assert client.post("/api/auth/register", json={"email": "new@example.com", "password": "testpass123"}).status_code == 409
    assert client.post("/api/auth/register", json={"email": "x@example.com", "password": "short"}).status_code == 422
    assert client.post("/api/auth/register", json={"email": "not-an-email", "password": "testpass123"}).status_code == 422
    token = client.post("/api/auth/login", data={"username": "NEW@example.com", "password": "testpass123"}).json()["access_token"]
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).json()["email"] == "new@example.com"


def test_protected_routes_need_a_valid_token(client):
    assert client.get("/api/repositories").status_code == 401
    assert client.get("/api/repositories", headers={"Authorization": "Bearer garbage"}).status_code == 401


def test_wrong_password_and_unknown_user_look_the_same(client):
    make_user(client, "a@example.com")
    wrong = client.post("/api/auth/login", data={"username": "a@example.com", "password": "nope-nope"})
    unknown = client.post("/api/auth/login", data={"username": "ghost@example.com", "password": "nope-nope"})
    assert wrong.status_code == unknown.status_code == 401 and wrong.json() == unknown.json()


def test_login_lockout_after_repeated_failures(client):
    make_user(client, "victim@example.com")
    for _ in range(5):
        assert client.post("/api/auth/login", data={"username": "victim@example.com", "password": "guess1234"}).status_code == 401
    blocked = client.post("/api/auth/login", data={"username": "victim@example.com", "password": "testpass123"})
    assert blocked.status_code == 429 and int(blocked.headers["Retry-After"]) > 0  # even the right password waits
    assert client.post("/api/auth/login", data={"username": "other@example.com", "password": "x"}).status_code == 401


def test_add_and_list_repositories(client, auth):
    bad = client.post("/api/repositories", json={"url": "https://gitlab.com/a/b"}, headers=auth)
    assert bad.status_code == 422
    assert client.post("/api/repositories", json={"url": "https://github.com/" + "a" * 600}, headers=auth).status_code == 422
    r = client.post("/api/repositories", json={"url": "github.com/Acme/Widgets.git"}, headers=auth)
    assert r.status_code == 201 and r.json()["full_name"] == "Acme/Widgets" and r.json()["latest_scan"] is None
    assert client.post("/api/repositories", json={"url": "https://github.com/acme/widgets"}, headers=auth).status_code == 409
    assert [x["full_name"] for x in client.get("/api/repositories", headers=auth).json()] == ["Acme/Widgets"]


def test_users_cannot_see_each_others_data(client, auth):
    rid = client.post("/api/repositories", json={"url": "https://github.com/acme/widgets"}, headers=auth).json()["id"]
    other = make_user(client, "other@example.com")
    assert client.get("/api/repositories", headers=other).json() == []
    for url in (f"/api/repositories/{rid}", f"/api/repositories/{rid}/trends", f"/api/repositories/{rid}/scans"):
        assert client.get(url, headers=other).status_code == 404  # 404, not 403: don't reveal it exists
    assert client.delete(f"/api/repositories/{rid}", headers=other).status_code == 404
    assert client.post(f"/api/repositories/{rid}/scans", headers=other).status_code == 404
    # ...but the other user may add the same public repo themselves
    assert client.post("/api/repositories", json={"url": "https://github.com/acme/widgets"}, headers=other).status_code == 201
