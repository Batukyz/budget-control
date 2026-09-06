from datetime import date

TODAY = date.today()
THIS_MONTH = TODAY.replace(day=1).isoformat()


def _months_ago(months: int) -> str:
    total = TODAY.year * 12 + (TODAY.month - 1) - months
    year, month = divmod(total, 12)
    return date(year, month + 1, 1).isoformat()


def test_monthly_trend_requires_auth(anon_client):
    assert anon_client.get("/reports/monthly-trend").status_code == 401


def test_monthly_trend_defaults_to_six_months(client):
    response = client.get("/reports/monthly-trend")
    assert response.status_code == 200
    assert len(response.json()) == 6


def test_monthly_trend_last_entry_is_current_month(client):
    client.post("/transactions", json={"amount": 1000, "type": "income", "occurred_on": THIS_MONTH})
    client.post("/transactions", json={"amount": 300, "type": "expense", "occurred_on": THIS_MONTH})

    response = client.get("/reports/monthly-trend", params={"months": 3})
    entries = response.json()
    current_key = f"{TODAY.year:04d}-{TODAY.month:02d}"
    assert entries[-1]["month"] == current_key
    assert entries[-1]["income"] == 1000
    assert entries[-1]["expense"] == 300


def test_monthly_trend_includes_empty_months_as_zero(client):
    response = client.get("/reports/monthly-trend", params={"months": 3})
    entries = response.json()
    assert all(e["income"] == 0 and e["expense"] == 0 for e in entries)


def test_monthly_trend_excludes_older_months(client):
    client.post("/transactions", json={"amount": 999, "type": "income", "occurred_on": _months_ago(5)})
    response = client.get("/reports/monthly-trend", params={"months": 2})
    total_income = sum(e["income"] for e in response.json())
    assert total_income == 0


def test_category_breakdown_requires_auth(anon_client):
    assert anon_client.get("/reports/category-breakdown").status_code == 401


def test_category_breakdown_defaults_to_current_month_expenses(client):
    client.post("/transactions", json={"amount": 200, "type": "expense", "category": "Market", "occurred_on": THIS_MONTH})
    client.post("/transactions", json={"amount": 100, "type": "expense", "category": "Ulaşım", "occurred_on": THIS_MONTH})
    client.post("/transactions", json={"amount": 5000, "type": "income", "occurred_on": THIS_MONTH})

    response = client.get("/reports/category-breakdown")
    assert response.status_code == 200
    body = response.json()
    assert body == [{"category": "Market", "amount": 200}, {"category": "Ulaşım", "amount": 100}]


def test_category_breakdown_groups_missing_category_as_diger(client):
    client.post("/transactions", json={"amount": 50, "type": "expense", "occurred_on": THIS_MONTH})
    response = client.get("/reports/category-breakdown")
    assert response.json() == [{"category": "Diğer", "amount": 50}]


def test_category_breakdown_supports_income_type(client):
    client.post("/transactions", json={"amount": 5000, "type": "income", "category": "Maaş", "occurred_on": THIS_MONTH})
    client.post("/transactions", json={"amount": 200, "type": "expense", "category": "Market", "occurred_on": THIS_MONTH})

    response = client.get("/reports/category-breakdown", params={"type": "income"})
    assert response.json() == [{"category": "Maaş", "amount": 5000}]


def test_category_breakdown_rejects_bad_month_format(client):
    response = client.get("/reports/category-breakdown", params={"month": "not-a-month"})
    assert response.status_code == 400


def test_category_breakdown_scoped_to_owner(make_authed_client):
    alice = make_authed_client(email="alice_report@example.com")
    bob = make_authed_client(email="bob_report@example.com")

    alice.post("/transactions", json={"amount": 100, "type": "expense", "category": "Market", "occurred_on": THIS_MONTH})
    bob.post("/transactions", json={"amount": 999, "type": "expense", "category": "Ulaşım", "occurred_on": THIS_MONTH})

    response = alice.get("/reports/category-breakdown")
    assert response.json() == [{"category": "Market", "amount": 100}]
