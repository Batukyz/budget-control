from datetime import date, timedelta

TODAY = date.today().isoformat()
IN_3_DAYS = (date.today() + timedelta(days=3)).isoformat()
IN_30_DAYS = (date.today() + timedelta(days=30)).isoformat()


def test_subscriptions_require_auth(anon_client):
    assert anon_client.get("/subscriptions").status_code == 401


def test_create_subscription(client):
    response = client.post(
        "/subscriptions",
        json={"name": "Netflix", "amount": 199.99, "billing_cycle": "monthly", "next_due_date": IN_3_DAYS},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Netflix"
    assert body["is_active"] is True
    assert body["billing_cycle"] == "monthly"


def test_create_subscription_defaults_billing_cycle_to_monthly(client):
    response = client.post("/subscriptions", json={"name": "Spotify", "amount": 55, "next_due_date": IN_3_DAYS})
    assert response.status_code == 201
    assert response.json()["billing_cycle"] == "monthly"


def test_list_subscriptions_sorted_by_next_due_date(client):
    client.post("/subscriptions", json={"name": "B", "amount": 10, "next_due_date": IN_30_DAYS})
    client.post("/subscriptions", json={"name": "A", "amount": 10, "next_due_date": IN_3_DAYS})

    response = client.get("/subscriptions")
    names = [s["name"] for s in response.json()]
    assert names == ["A", "B"]


def test_update_subscription(client):
    created = client.post(
        "/subscriptions", json={"name": "Netflix", "amount": 199.99, "next_due_date": IN_3_DAYS}
    ).json()
    response = client.put(f"/subscriptions/{created['id']}", json={"is_active": False})
    assert response.status_code == 200
    assert response.json()["is_active"] is False
    assert response.json()["name"] == "Netflix"


def test_delete_subscription(client):
    created = client.post(
        "/subscriptions", json={"name": "Netflix", "amount": 199.99, "next_due_date": IN_3_DAYS}
    ).json()
    response = client.delete(f"/subscriptions/{created['id']}")
    assert response.status_code == 204
    assert client.get(f"/subscriptions/{created['id']}").status_code == 404


def test_subscriptions_scoped_to_owner(make_authed_client):
    alice = make_authed_client(email="alice_sub@example.com")
    bob = make_authed_client(email="bob_sub@example.com")

    alice.post("/subscriptions", json={"name": "Netflix", "amount": 10, "next_due_date": IN_3_DAYS})
    bob.post("/subscriptions", json={"name": "Spotify", "amount": 10, "next_due_date": IN_3_DAYS})

    assert len(alice.get("/subscriptions").json()) == 1
    assert alice.get("/subscriptions").json()[0]["name"] == "Netflix"
