from datetime import date, timedelta

TODAY = date.today().isoformat()
YESTERDAY = (date.today() - timedelta(days=1)).isoformat()


def test_transactions_require_auth(anon_client):
    assert anon_client.get("/transactions").status_code == 401
    assert anon_client.post("/transactions", json={"amount": 10, "type": "expense"}).status_code == 401


def test_create_transaction_defaults_to_today(client):
    response = client.post("/transactions", json={"amount": 42.5, "type": "expense"})
    assert response.status_code == 201
    body = response.json()
    assert body["amount"] == 42.5
    assert body["type"] == "expense"
    assert body["occurred_on"] == TODAY


def test_create_transaction_with_all_fields(client):
    response = client.post(
        "/transactions",
        json={
            "amount": 15,
            "type": "income",
            "category": "Maaş",
            "note": "Ağustos maaşı",
            "occurred_on": YESTERDAY,
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["category"] == "Maaş"
    assert body["note"] == "Ağustos maaşı"
    assert body["occurred_on"] == YESTERDAY


def test_create_transaction_rejects_non_positive_amount(client):
    response = client.post("/transactions", json={"amount": 0, "type": "expense"})
    assert response.status_code == 422


def test_create_transaction_rejects_invalid_type(client):
    response = client.post("/transactions", json={"amount": 10, "type": "savings"})
    assert response.status_code == 422


def test_list_transactions_sorted_newest_first(client):
    client.post("/transactions", json={"amount": 1, "type": "expense", "occurred_on": YESTERDAY})
    client.post("/transactions", json={"amount": 2, "type": "expense", "occurred_on": TODAY})

    response = client.get("/transactions")
    assert response.status_code == 200
    dates = [t["occurred_on"] for t in response.json()]
    assert dates == [TODAY, YESTERDAY]


def test_get_transaction(client):
    created = client.post("/transactions", json={"amount": 5, "type": "expense"}).json()
    response = client.get(f"/transactions/{created['id']}")
    assert response.status_code == 200
    assert response.json()["id"] == created["id"]


def test_get_transaction_not_found(client):
    assert client.get("/transactions/999").status_code == 404


def test_update_transaction(client):
    created = client.post("/transactions", json={"amount": 5, "type": "expense"}).json()
    response = client.put(f"/transactions/{created['id']}", json={"amount": 9, "note": "güncellendi"})
    assert response.status_code == 200
    body = response.json()
    assert body["amount"] == 9
    assert body["note"] == "güncellendi"
    assert body["type"] == "expense"  # untouched fields stay the same


def test_delete_transaction(client):
    created = client.post("/transactions", json={"amount": 5, "type": "expense"}).json()
    response = client.delete(f"/transactions/{created['id']}")
    assert response.status_code == 204
    assert client.get(f"/transactions/{created['id']}").status_code == 404


def test_list_transactions_filters_by_type_and_category(client):
    client.post("/transactions", json={"amount": 1, "type": "expense", "category": "Market"})
    client.post("/transactions", json={"amount": 2, "type": "expense", "category": "Ulaşım"})
    client.post("/transactions", json={"amount": 3, "type": "income", "category": "Market"})

    response = client.get("/transactions", params={"type": "expense", "category": "Market"})
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["category"] == "Market"
    assert body[0]["type"] == "expense"


def test_list_transactions_filters_by_date_range(client):
    client.post("/transactions", json={"amount": 1, "type": "expense", "occurred_on": YESTERDAY})
    client.post("/transactions", json={"amount": 2, "type": "expense", "occurred_on": TODAY})

    response = client.get("/transactions", params={"from_date": TODAY})
    assert response.status_code == 200
    dates = [t["occurred_on"] for t in response.json()]
    assert dates == [TODAY]


def test_list_transactions_paginates(client):
    for i in range(5):
        client.post("/transactions", json={"amount": i + 1, "type": "expense", "occurred_on": TODAY})

    first_page = client.get("/transactions", params={"limit": 2, "skip": 0}).json()
    second_page = client.get("/transactions", params={"limit": 2, "skip": 2}).json()
    assert len(first_page) == 2
    assert len(second_page) == 2
    assert {t["id"] for t in first_page}.isdisjoint({t["id"] for t in second_page})


def test_transactions_scoped_to_owner(make_authed_client):
    alice = make_authed_client(email="alice_tx@example.com")
    bob = make_authed_client(email="bob_tx@example.com")

    alice_tx = alice.post("/transactions", json={"amount": 1, "type": "expense"}).json()
    bob.post("/transactions", json={"amount": 2, "type": "expense"})

    assert len(bob.get("/transactions").json()) == 1
    assert bob.get(f"/transactions/{alice_tx['id']}").status_code == 404
