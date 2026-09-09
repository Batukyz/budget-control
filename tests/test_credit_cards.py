from datetime import date

TODAY = date.today()


def test_credit_cards_require_auth(anon_client):
    assert anon_client.get("/credit-cards").status_code == 401


def test_create_credit_card(client):
    response = client.post(
        "/credit-cards",
        json={
            "bank_name": "Garanti BBVA",
            "card_name": "Bonus",
            "limit_amount": 20000,
            "current_debt": 5000,
            "statement_day": 15,
            "due_day": 25,
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["bank_name"] == "Garanti BBVA"
    assert body["available_limit"] == 15000
    assert "next_statement_date" in body
    assert "next_due_date" in body


def test_create_credit_card_defaults_current_debt_to_zero(client):
    response = client.post(
        "/credit-cards",
        json={"bank_name": "Akbank", "limit_amount": 10000, "statement_day": 5, "due_day": 20},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["current_debt"] == 0
    assert body["available_limit"] == 10000


def test_create_credit_card_rejects_invalid_day(client):
    response = client.post(
        "/credit-cards",
        json={"bank_name": "Akbank", "limit_amount": 10000, "statement_day": 32, "due_day": 20},
    )
    assert response.status_code == 422


def test_create_credit_card_rejects_empty_bank_name(client):
    response = client.post(
        "/credit-cards",
        json={"bank_name": "", "limit_amount": 10000, "statement_day": 5, "due_day": 20},
    )
    assert response.status_code == 422


def test_next_occurrence_of_day_rolls_to_next_month_when_day_passed(client):
    past_day = TODAY.day - 1 if TODAY.day > 1 else 28
    response = client.post(
        "/credit-cards",
        json={"bank_name": "Akbank", "limit_amount": 10000, "statement_day": past_day, "due_day": past_day},
    )
    body = response.json()
    assert date.fromisoformat(body["next_statement_date"]) >= TODAY
    assert date.fromisoformat(body["next_due_date"]) >= TODAY


def test_update_credit_card(client):
    created = client.post(
        "/credit-cards",
        json={"bank_name": "Akbank", "limit_amount": 10000, "statement_day": 5, "due_day": 20},
    ).json()
    response = client.put(f"/credit-cards/{created['id']}", json={"current_debt": 2500})
    assert response.status_code == 200
    body = response.json()
    assert body["current_debt"] == 2500
    assert body["available_limit"] == 7500
    assert body["bank_name"] == "Akbank"


def test_delete_credit_card(client):
    created = client.post(
        "/credit-cards",
        json={"bank_name": "Akbank", "limit_amount": 10000, "statement_day": 5, "due_day": 20},
    ).json()
    response = client.delete(f"/credit-cards/{created['id']}")
    assert response.status_code == 204
    assert client.get(f"/credit-cards/{created['id']}").status_code == 404


def test_credit_cards_scoped_to_owner(make_authed_client):
    alice = make_authed_client(email="alice_card@example.com")
    bob = make_authed_client(email="bob_card@example.com")

    alice.post("/credit-cards", json={"bank_name": "Alice Bank", "limit_amount": 1000, "statement_day": 1, "due_day": 10})
    bob.post("/credit-cards", json={"bank_name": "Bob Bank", "limit_amount": 2000, "statement_day": 1, "due_day": 10})

    cards = alice.get("/credit-cards").json()
    assert len(cards) == 1
    assert cards[0]["bank_name"] == "Alice Bank"
