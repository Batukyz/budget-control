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


def test_list_subscriptions_filters_by_active_status(client):
    active = client.post("/subscriptions", json={"name": "Active", "amount": 10, "next_due_date": IN_3_DAYS}).json()
    cancelled = client.post(
        "/subscriptions", json={"name": "Cancelled", "amount": 10, "next_due_date": IN_3_DAYS}
    ).json()
    client.put(f"/subscriptions/{cancelled['id']}", json={"is_active": False})

    response = client.get("/subscriptions", params={"is_active": True})
    names = [s["name"] for s in response.json()]
    assert names == ["Active"]


def test_list_subscriptions_paginates(client):
    for i in range(5):
        client.post("/subscriptions", json={"name": f"Sub{i}", "amount": 10, "next_due_date": IN_3_DAYS})

    first_page = client.get("/subscriptions", params={"limit": 2, "skip": 0}).json()
    second_page = client.get("/subscriptions", params={"limit": 2, "skip": 2}).json()
    assert len(first_page) == 2
    assert len(second_page) == 2
    assert {s["id"] for s in first_page}.isdisjoint({s["id"] for s in second_page})


def test_subscriptions_scoped_to_owner(make_authed_client):
    alice = make_authed_client(email="alice_sub@example.com")
    bob = make_authed_client(email="bob_sub@example.com")

    alice.post("/subscriptions", json={"name": "Netflix", "amount": 10, "next_due_date": IN_3_DAYS})
    bob.post("/subscriptions", json={"name": "Spotify", "amount": 10, "next_due_date": IN_3_DAYS})

    assert len(alice.get("/subscriptions").json()) == 1
    assert alice.get("/subscriptions").json()[0]["name"] == "Netflix"


def test_pay_subscription_requires_auth(anon_client):
    assert anon_client.post("/subscriptions/1/pay").status_code == 401


def test_pay_subscription_creates_transaction_and_advances_due_date(client):
    created = client.post(
        "/subscriptions",
        json={"name": "Netflix", "amount": 199.99, "category": "Eğlence", "billing_cycle": "monthly", "next_due_date": TODAY},
    ).json()

    response = client.post(f"/subscriptions/{created['id']}/pay")
    assert response.status_code == 200
    body = response.json()

    assert body["transaction"]["amount"] == 199.99
    assert body["transaction"]["type"] == "expense"
    assert body["transaction"]["category"] == "Eğlence"
    assert body["transaction"]["note"] == "Netflix"
    assert body["transaction"]["occurred_on"] == TODAY

    assert body["subscription"]["next_due_date"] > TODAY

    transactions = client.get("/transactions").json()
    assert len(transactions) == 1


def test_pay_subscription_advances_weekly_by_seven_days(client):
    created = client.post(
        "/subscriptions", json={"name": "Weekly", "amount": 10, "billing_cycle": "weekly", "next_due_date": TODAY}
    ).json()
    response = client.post(f"/subscriptions/{created['id']}/pay")
    body = response.json()
    expected = (date.today() + timedelta(days=7)).isoformat()
    assert body["subscription"]["next_due_date"] == expected


def test_pay_subscription_not_found(client):
    assert client.post("/subscriptions/999/pay").status_code == 404


def test_pay_subscription_scoped_to_owner(make_authed_client):
    alice = make_authed_client(email="alice_pay@example.com")
    bob = make_authed_client(email="bob_pay@example.com")
    created = alice.post("/subscriptions", json={"name": "Netflix", "amount": 10, "next_due_date": TODAY}).json()

    response = bob.post(f"/subscriptions/{created['id']}/pay")
    assert response.status_code == 404
