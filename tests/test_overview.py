from datetime import date, timedelta

TODAY = date.today().isoformat()
IN_3_DAYS = (date.today() + timedelta(days=3)).isoformat()
IN_30_DAYS = (date.today() + timedelta(days=30)).isoformat()
LAST_MONTH = (date.today().replace(day=1) - timedelta(days=1)).isoformat()


def test_overview_requires_auth(anon_client):
    assert anon_client.get("/overview").status_code == 401


def test_overview_empty_state(client):
    response = client.get("/overview")
    assert response.status_code == 200
    assert response.json() == {
        "month_income": 0.0,
        "month_expense": 0.0,
        "net_balance": 0.0,
        "monthly_subscription_cost": 0.0,
        "upcoming_subscriptions": 0,
        "budgets_over_limit": 0,
    }


def test_overview_sums_this_months_transactions(client):
    client.post("/transactions", json={"amount": 1000, "type": "income", "occurred_on": TODAY})
    client.post("/transactions", json={"amount": 250, "type": "expense", "occurred_on": TODAY})
    # a transaction from last month should not be counted
    client.post("/transactions", json={"amount": 999, "type": "expense", "occurred_on": LAST_MONTH})

    response = client.get("/overview")
    body = response.json()
    assert body["month_income"] == 1000
    assert body["month_expense"] == 250
    assert body["net_balance"] == 750


def test_overview_monthly_subscription_cost_normalizes_cycles(client):
    client.post(
        "/subscriptions",
        json={"name": "Monthly", "amount": 100, "billing_cycle": "monthly", "next_due_date": IN_3_DAYS},
    )
    client.post(
        "/subscriptions",
        json={"name": "Yearly", "amount": 1200, "billing_cycle": "yearly", "next_due_date": IN_30_DAYS},
    )

    response = client.get("/overview")
    # 100 (monthly) + 1200/12 (yearly normalized) = 200
    assert response.json()["monthly_subscription_cost"] == 200.0


def test_overview_excludes_inactive_subscriptions(client):
    created = client.post(
        "/subscriptions", json={"name": "Cancelled", "amount": 100, "next_due_date": IN_3_DAYS}
    ).json()
    client.put(f"/subscriptions/{created['id']}", json={"is_active": False})

    response = client.get("/overview")
    assert response.json()["monthly_subscription_cost"] == 0.0


def test_overview_counts_upcoming_subscriptions_within_7_days(client):
    client.post("/subscriptions", json={"name": "Soon", "amount": 10, "next_due_date": IN_3_DAYS})
    client.post("/subscriptions", json={"name": "Later", "amount": 10, "next_due_date": IN_30_DAYS})

    response = client.get("/overview")
    assert response.json()["upcoming_subscriptions"] == 1


def test_overview_counts_budgets_over_limit(client):
    client.post("/budgets", json={"category": "Market", "monthly_limit": 100})
    client.post("/budgets", json={"category": "Ulaşım", "monthly_limit": 100})
    client.post("/transactions", json={"amount": 150, "type": "expense", "category": "Market", "occurred_on": TODAY})
    client.post("/transactions", json={"amount": 20, "type": "expense", "category": "Ulaşım", "occurred_on": TODAY})

    response = client.get("/overview")
    assert response.json()["budgets_over_limit"] == 1


def test_overview_budgets_over_limit_ignores_category_case(client):
    client.post("/budgets", json={"category": "Market", "monthly_limit": 100})
    client.post("/transactions", json={"amount": 150, "type": "expense", "category": "market", "occurred_on": TODAY})

    response = client.get("/overview")
    assert response.json()["budgets_over_limit"] == 1


def test_overview_scoped_to_owner(make_authed_client):
    alice = make_authed_client(email="alice_ov@example.com")
    bob = make_authed_client(email="bob_ov@example.com")

    alice.post("/transactions", json={"amount": 500, "type": "income", "occurred_on": TODAY})

    assert alice.get("/overview").json()["month_income"] == 500
    assert bob.get("/overview").json()["month_income"] == 0
