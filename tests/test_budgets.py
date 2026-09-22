from datetime import date

TODAY = date.today().isoformat()


def test_budgets_require_auth(anon_client):
    assert anon_client.get("/budgets").status_code == 401
    assert anon_client.post("/budgets", json={"monthly_limit": 100}).status_code == 401


def test_create_category_budget(client):
    response = client.post("/budgets", json={"category": "Market", "monthly_limit": 500})
    assert response.status_code == 201
    body = response.json()
    assert body["category"] == "Market"
    assert body["monthly_limit"] == 500


def test_create_overall_budget_with_no_category(client):
    response = client.post("/budgets", json={"monthly_limit": 5000})
    assert response.status_code == 201
    assert response.json()["category"] is None


def test_create_budget_rejects_duplicate_category(client):
    client.post("/budgets", json={"category": "Market", "monthly_limit": 500})
    response = client.post("/budgets", json={"category": "Market", "monthly_limit": 300})
    assert response.status_code == 400


def test_create_budget_rejects_non_positive_limit(client):
    response = client.post("/budgets", json={"category": "Market", "monthly_limit": 0})
    assert response.status_code == 422


def test_list_budgets_reports_spend_status(client):
    client.post("/budgets", json={"category": "Market", "monthly_limit": 100})
    client.post("/transactions", json={"amount": 40, "type": "expense", "category": "Market", "occurred_on": TODAY})

    response = client.get("/budgets")
    assert response.status_code == 200
    body = response.json()[0]
    assert body["spent_this_month"] == 40
    assert body["remaining"] == 60
    assert body["is_over_limit"] is False


def test_list_budgets_flags_over_limit(client):
    client.post("/budgets", json={"category": "Market", "monthly_limit": 100})
    client.post("/transactions", json={"amount": 150, "type": "expense", "category": "Market", "occurred_on": TODAY})

    response = client.get("/budgets")
    body = response.json()[0]
    assert body["spent_this_month"] == 150
    assert body["remaining"] == -50
    assert body["is_over_limit"] is True


def test_overall_budget_counts_all_expense_categories(client):
    client.post("/budgets", json={"monthly_limit": 100})
    client.post("/transactions", json={"amount": 60, "type": "expense", "category": "Market", "occurred_on": TODAY})
    client.post("/transactions", json={"amount": 60, "type": "expense", "category": "Ulaşım", "occurred_on": TODAY})
    client.post("/transactions", json={"amount": 1000, "type": "income", "occurred_on": TODAY})

    response = client.get("/budgets")
    body = response.json()[0]
    assert body["spent_this_month"] == 120
    assert body["is_over_limit"] is True


def test_budget_spend_matching_ignores_category_case_and_whitespace(client):
    client.post("/budgets", json={"category": "Market", "monthly_limit": 100})
    client.post("/transactions", json={"amount": 40, "type": "expense", "category": "market", "occurred_on": TODAY})
    client.post("/transactions", json={"amount": 10, "type": "expense", "category": " Market ", "occurred_on": TODAY})

    response = client.get("/budgets")
    body = response.json()[0]
    assert body["spent_this_month"] == 50


def test_create_budget_rejects_duplicate_category_case_insensitive(client):
    client.post("/budgets", json={"category": "Market", "monthly_limit": 500})
    response = client.post("/budgets", json={"category": "market", "monthly_limit": 300})
    assert response.status_code == 400


def test_update_budget_limit(client):
    created = client.post("/budgets", json={"category": "Market", "monthly_limit": 100}).json()
    response = client.put(f"/budgets/{created['id']}", json={"monthly_limit": 200})
    assert response.status_code == 200
    assert response.json()["monthly_limit"] == 200


def test_update_budget_not_found(client):
    assert client.put("/budgets/999", json={"monthly_limit": 200}).status_code == 404


def test_delete_budget(client):
    created = client.post("/budgets", json={"category": "Market", "monthly_limit": 100}).json()
    response = client.delete(f"/budgets/{created['id']}")
    assert response.status_code == 204
    assert client.get("/budgets").json() == []


def test_budgets_scoped_to_owner(make_authed_client):
    alice = make_authed_client(email="alice_budget@example.com")
    bob = make_authed_client(email="bob_budget@example.com")

    alice_budget = alice.post("/budgets", json={"category": "Market", "monthly_limit": 100}).json()
    bob.post("/budgets", json={"category": "Market", "monthly_limit": 200})

    assert len(bob.get("/budgets").json()) == 1
    assert bob.put(f"/budgets/{alice_budget['id']}", json={"monthly_limit": 1}).status_code == 404


def test_list_budgets_percentage_and_near_limit(client):
    client.post("/budgets", json={"category": "Restoran", "monthly_limit": 100})
    # 85 TL spent -> 85%, near limit
    client.post("/transactions", json={"amount": 85, "type": "expense", "category": "Restoran", "occurred_on": TODAY})

    res = client.get("/budgets").json()
    b = next(item for item in res if item["category"] == "Restoran")
    assert b["spent_this_month"] == 85.0
    assert b["spent_percentage"] == 85.0
    assert b["is_near_limit"] is True
    assert b["is_over_limit"] is False


def test_list_budgets_with_historical_month(client):
    client.post("/budgets", json={"category": "Eğlence", "monthly_limit": 200})
    client.post("/transactions", json={"amount": 75, "type": "expense", "category": "Eğlence", "occurred_on": "2025-06-15"})
    client.post("/transactions", json={"amount": 50, "type": "expense", "category": "Eğlence", "occurred_on": TODAY})

    # June 2025
    res_june = client.get("/budgets?month=2025-06").json()
    b_june = next(item for item in res_june if item["category"] == "Eğlence")
    assert b_june["spent_this_month"] == 75.0
    assert b_june["remaining"] == 125.0

    # Current month
    res_now = client.get("/budgets").json()
    b_now = next(item for item in res_now if item["category"] == "Eğlence")
    assert b_now["spent_this_month"] == 50.0


def test_list_budgets_invalid_month_format(client):
    assert client.get("/budgets?month=2025/06").status_code == 400
    assert client.get("/budgets?month=abc").status_code == 400

