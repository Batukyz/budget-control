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
