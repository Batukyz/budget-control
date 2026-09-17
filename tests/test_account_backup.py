from datetime import date, timedelta

TODAY = date.today().isoformat()
IN_3_DAYS = (date.today() + timedelta(days=3)).isoformat()


def test_export_requires_auth(anon_client):
    assert anon_client.get("/account/export").status_code == 401


def test_export_empty_account(client):
    response = client.get("/account/export")
    assert response.status_code == 200
    body = response.json()
    assert body["transactions"] == []
    assert body["subscriptions"] == []
    assert body["recurring_transactions"] == []
    assert body["credit_cards"] == []
    assert body["categories"] == []
    assert body["budgets"] == []
    assert body["exported_at"] is not None


def test_export_includes_all_data_types(client):
    client.post("/transactions", json={"amount": 100, "type": "expense", "category": "Market", "occurred_on": TODAY})
    client.post("/subscriptions", json={"name": "Netflix", "amount": 199.99, "next_due_date": TODAY})
    client.post("/recurring-transactions", json={"name": "Maaş", "amount": 25000, "type": "income", "next_due_date": IN_3_DAYS})
    client.post("/credit-cards", json={"bank_name": "Garanti BBVA", "limit_amount": 10000, "statement_day": 5, "due_day": 20})
    client.post("/categories", json={"name": "Market", "type": "expense"})
    client.post("/budgets", json={"category": "Market", "monthly_limit": 500})

    body = client.get("/account/export").json()
    assert len(body["transactions"]) == 1
    assert len(body["subscriptions"]) == 1
    assert len(body["recurring_transactions"]) == 1
    assert len(body["credit_cards"]) == 1
    assert len(body["categories"]) == 1
    assert len(body["budgets"]) == 1
    assert body["transactions"][0]["category"] == "Market"


def test_export_scoped_to_owner(make_authed_client):
    alice = make_authed_client(email="alice_backup@example.com")
    bob = make_authed_client(email="bob_backup@example.com")
    alice.post("/transactions", json={"amount": 100, "type": "expense", "occurred_on": TODAY})

    assert len(bob.get("/account/export").json()["transactions"]) == 0
    assert len(alice.get("/account/export").json()["transactions"]) == 1


def test_import_requires_auth(anon_client):
    assert anon_client.post("/account/import", json={}).status_code == 401


def test_import_creates_records_from_backup(client):
    backup = {
        "transactions": [{"amount": 100, "type": "expense", "category": "Market", "occurred_on": TODAY}],
        "subscriptions": [{"name": "Netflix", "amount": 199.99, "billing_cycle": "monthly", "next_due_date": TODAY}],
        "recurring_transactions": [{"name": "Maaş", "amount": 25000, "type": "income", "frequency": "monthly", "next_due_date": IN_3_DAYS}],
        "credit_cards": [{"bank_name": "Akbank", "limit_amount": 10000, "statement_day": 5, "due_day": 20}],
        "categories": [{"name": "Market", "type": "expense"}],
        "budgets": [{"category": "Market", "monthly_limit": 500}],
    }
    response = client.post("/account/import", json=backup)
    assert response.status_code == 200
    body = response.json()
    assert body == {
        "transactions": 1,
        "subscriptions": 1,
        "recurring_transactions": 1,
        "credit_cards": 1,
        "categories": 1,
        "budgets": 1,
    }
    assert len(client.get("/transactions").json()) == 1
    assert len(client.get("/subscriptions").json()) == 1
    assert len(client.get("/recurring-transactions").json()) == 1
    assert len(client.get("/credit-cards").json()) == 1
    assert len(client.get("/categories").json()) == 1
    assert len(client.get("/budgets").json()) == 1


def test_import_skips_duplicate_categories(client):
    client.post("/categories", json={"name": "Market", "type": "expense"})
    response = client.post("/account/import", json={"categories": [{"name": "market"}]})
    assert response.json()["categories"] == 0
    assert len(client.get("/categories").json()) == 1


def test_import_skips_duplicate_budget_categories(client):
    client.post("/budgets", json={"category": "Market", "monthly_limit": 100})
    response = client.post("/account/import", json={"budgets": [{"category": "market", "monthly_limit": 200}]})
    assert response.json()["budgets"] == 0
    assert len(client.get("/budgets").json()) == 1


def test_export_then_import_round_trip_preserves_counts(client):
    client.post("/transactions", json={"amount": 100, "type": "expense", "occurred_on": TODAY})
    client.post("/subscriptions", json={"name": "Netflix", "amount": 10, "next_due_date": TODAY})

    backup = client.get("/account/export").json()
    result = client.post("/account/import", json=backup)
    assert result.json()["transactions"] == 1
    assert result.json()["subscriptions"] == 1
    # importing on top doubles transactions (no dedup for those) but not categories/budgets
    assert len(client.get("/transactions").json()) == 2
    repeat = client.post("/account/import", json=backup)
    assert repeat.json()["transactions"] == 0
    assert len(client.get("/transactions").json()) == 2


def test_backup_restores_credit_card_and_recurring_transaction_links(client):
    card = client.post(
        "/credit-cards", json={"bank_name": "Bank", "limit_amount": 1000, "statement_day": 5, "due_day": 20}
    ).json()
    recurring = client.post(
        "/recurring-transactions", json={"name": "Rent", "amount": 100, "type": "expense", "next_due_date": IN_3_DAYS}
    ).json()
    client.post(
        "/transactions",
        json={"amount": 50, "type": "expense", "occurred_on": TODAY, "credit_card_id": card["id"]},
    )
    client.put(f"/recurring-transactions/{recurring['id']}", json={"next_due_date": TODAY})
    client.post("/recurring-transactions/process-due")
    backup = client.get("/account/export").json()
    target = client.post("/auth/register", json={"email": "restore@example.com", "password": "testpassword123"})
    assert target.status_code == 201
    login = client.post("/auth/login", data={"username": "restore@example.com", "password": "testpassword123"}).json()
    client.headers["Authorization"] = f"Bearer {login['access_token']}"
    assert client.post("/account/import", json=backup).status_code == 200
    restored = client.get("/transactions").json()
    assert any(t["credit_card_id"] is not None for t in restored)
    assert any(t["recurring_transaction_id"] is not None for t in restored)


def test_import_does_not_leak_across_owners(make_authed_client):
    alice = make_authed_client(email="alice_import@example.com")
    bob = make_authed_client(email="bob_import@example.com")
    alice.post("/account/import", json={"transactions": [{"amount": 100, "type": "expense", "occurred_on": TODAY}]})

    assert len(bob.get("/transactions").json()) == 0
    assert len(alice.get("/transactions").json()) == 1
