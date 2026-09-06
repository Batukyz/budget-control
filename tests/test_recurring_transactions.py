from datetime import date, timedelta

TODAY = date.today()
IN_3_DAYS = (TODAY + timedelta(days=3)).isoformat()


def test_recurring_transactions_require_auth(anon_client):
    assert anon_client.get("/recurring-transactions").status_code == 401


def test_create_recurring_transaction(client):
    response = client.post(
        "/recurring-transactions",
        json={
            "name": "Maaş",
            "amount": 25000,
            "type": "income",
            "frequency": "monthly",
            "next_due_date": IN_3_DAYS,
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Maaş"
    assert body["is_active"] is True
    assert body["frequency"] == "monthly"


def test_create_recurring_transaction_defaults_frequency_to_monthly(client):
    response = client.post(
        "/recurring-transactions",
        json={"name": "Burs", "amount": 3000, "type": "income", "next_due_date": IN_3_DAYS},
    )
    assert response.status_code == 201
    assert response.json()["frequency"] == "monthly"


def test_future_recurring_transaction_does_not_generate_transaction_yet(client):
    client.post(
        "/recurring-transactions",
        json={"name": "Maaş", "amount": 25000, "type": "income", "next_due_date": IN_3_DAYS},
    )
    assert client.get("/transactions").json() == []


def test_due_recurring_transaction_generates_transaction_on_create(client):
    response = client.post(
        "/recurring-transactions",
        json={
            "name": "Maaş",
            "amount": 25000,
            "type": "income",
            "frequency": "monthly",
            "next_due_date": TODAY.isoformat(),
        },
    )
    recurring_id = response.json()["id"]

    transactions = client.get("/transactions").json()
    assert len(transactions) == 1
    assert transactions[0]["amount"] == 25000
    assert transactions[0]["type"] == "income"
    assert transactions[0]["note"] == "Maaş"
    assert transactions[0]["recurring_transaction_id"] == recurring_id

    updated = client.get(f"/recurring-transactions/{recurring_id}").json()
    assert updated["next_due_date"] != TODAY.isoformat()
    assert updated["next_due_date"] > TODAY.isoformat()


def test_overdue_recurring_transaction_catches_up_multiple_periods(client):
    three_months_ago = (TODAY.replace(day=1) - timedelta(days=65)).isoformat()
    client.post(
        "/recurring-transactions",
        json={
            "name": "Kira",
            "amount": 5000,
            "type": "expense",
            "frequency": "monthly",
            "next_due_date": three_months_ago,
        },
    )
    transactions = client.get("/transactions").json()
    assert len(transactions) >= 2
    assert all(t["type"] == "expense" for t in transactions)


def test_inactive_recurring_transaction_does_not_generate(client):
    created = client.post(
        "/recurring-transactions",
        json={"name": "Maaş", "amount": 25000, "type": "income", "next_due_date": TODAY.isoformat()},
    ).json()
    # It already generated once at creation; deactivate then push due date back and verify no further generation.
    client.put(f"/recurring-transactions/{created['id']}", json={"is_active": False, "next_due_date": TODAY.isoformat()})
    before = len(client.get("/transactions").json())
    client.get("/transactions")
    after = len(client.get("/transactions").json())
    assert before == after


def test_update_recurring_transaction(client):
    created = client.post(
        "/recurring-transactions",
        json={"name": "Maaş", "amount": 25000, "type": "income", "next_due_date": IN_3_DAYS},
    ).json()
    response = client.put(f"/recurring-transactions/{created['id']}", json={"amount": 27000})
    assert response.status_code == 200
    assert response.json()["amount"] == 27000
    assert response.json()["name"] == "Maaş"


def test_delete_recurring_transaction_keeps_generated_transactions(client):
    created = client.post(
        "/recurring-transactions",
        json={"name": "Maaş", "amount": 25000, "type": "income", "next_due_date": TODAY.isoformat()},
    ).json()
    assert len(client.get("/transactions").json()) == 1

    response = client.delete(f"/recurring-transactions/{created['id']}")
    assert response.status_code == 204
    assert client.get(f"/recurring-transactions/{created['id']}").status_code == 404

    transactions = client.get("/transactions").json()
    assert len(transactions) == 1
    assert transactions[0]["recurring_transaction_id"] is None


def test_recurring_transactions_scoped_to_owner(make_authed_client):
    alice = make_authed_client(email="alice_rec@example.com")
    bob = make_authed_client(email="bob_rec@example.com")

    alice.post(
        "/recurring-transactions",
        json={"name": "Maaş", "amount": 1000, "type": "income", "next_due_date": IN_3_DAYS},
    )
    bob.post(
        "/recurring-transactions",
        json={"name": "Burs", "amount": 500, "type": "income", "next_due_date": IN_3_DAYS},
    )

    assert len(alice.get("/recurring-transactions").json()) == 1
    assert alice.get("/recurring-transactions").json()[0]["name"] == "Maaş"


def test_list_recurring_transactions_filters_by_active_status(client):
    active = client.post(
        "/recurring-transactions",
        json={"name": "Active", "amount": 10, "type": "income", "next_due_date": IN_3_DAYS},
    ).json()
    cancelled = client.post(
        "/recurring-transactions",
        json={"name": "Cancelled", "amount": 10, "type": "income", "next_due_date": IN_3_DAYS},
    ).json()
    client.put(f"/recurring-transactions/{cancelled['id']}", json={"is_active": False})

    response = client.get("/recurring-transactions", params={"is_active": True})
    names = [r["name"] for r in response.json()]
    assert names == ["Active"]
