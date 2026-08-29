def test_register(anon_client):
    response = anon_client.post(
        "/auth/register", json={"email": "new@example.com", "password": "testpassword123"}
    )
    assert response.status_code == 201
    assert response.json()["email"] == "new@example.com"


def test_register_duplicate_email(anon_client):
    anon_client.post(
        "/auth/register", json={"email": "dup@example.com", "password": "testpassword123"}
    )
    response = anon_client.post(
        "/auth/register", json={"email": "dup@example.com", "password": "anotherpassword"}
    )
    assert response.status_code == 400


def test_login(anon_client):
    anon_client.post(
        "/auth/register", json={"email": "login@example.com", "password": "testpassword123"}
    )
    response = anon_client.post(
        "/auth/login", data={"username": "login@example.com", "password": "testpassword123"}
    )
    assert response.status_code == 200
    body = response.json()
    assert "access_token" in body
    assert "refresh_token" in body


def test_login_wrong_password(anon_client):
    anon_client.post(
        "/auth/register", json={"email": "wrongpw@example.com", "password": "testpassword123"}
    )
    response = anon_client.post(
        "/auth/login", data={"username": "wrongpw@example.com", "password": "nope12345"}
    )
    assert response.status_code == 401


def test_me_requires_auth(anon_client):
    assert anon_client.get("/me").status_code == 401


def test_me(client):
    response = client.get("/me")
    assert response.status_code == 200
    assert "email" in response.json()


def test_refresh_token_flow(anon_client):
    anon_client.post(
        "/auth/register", json={"email": "refresh@example.com", "password": "testpassword123"}
    )
    login = anon_client.post(
        "/auth/login", data={"username": "refresh@example.com", "password": "testpassword123"}
    )
    refresh_token = login.json()["refresh_token"]

    response = anon_client.post("/auth/refresh", json={"refresh_token": refresh_token})
    assert response.status_code == 200
    new_access_token = response.json()["access_token"]
    me = anon_client.get("/me", headers={"Authorization": f"Bearer {new_access_token}"})
    assert me.status_code == 200
    assert me.json()["email"] == "refresh@example.com"

    # the old refresh token is revoked after use
    reuse = anon_client.post("/auth/refresh", json={"refresh_token": refresh_token})
    assert reuse.status_code == 401


def test_logout_revokes_refresh_token(anon_client):
    anon_client.post(
        "/auth/register", json={"email": "logout@example.com", "password": "testpassword123"}
    )
    login = anon_client.post(
        "/auth/login", data={"username": "logout@example.com", "password": "testpassword123"}
    )
    refresh_token = login.json()["refresh_token"]

    logout = anon_client.post("/auth/logout", json={"refresh_token": refresh_token})
    assert logout.status_code == 204

    response = anon_client.post("/auth/refresh", json={"refresh_token": refresh_token})
    assert response.status_code == 401
