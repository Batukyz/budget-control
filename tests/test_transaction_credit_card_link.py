def _make_card(client, limit_amount=10000, current_debt=0):
    return client.post(
        "/credit-cards",
        json={"bank_name": "Garanti BBVA", "limit_amount": limit_amount, "current_debt": current_debt, "statement_day": 15, "due_day": 25},
    ).json()


def test_expense_linked_to_card_increases_current_debt(client):
    card = _make_card(client)
    response = client.post("/transactions", json={"amount": 250, "type": "expense", "credit_card_id": card["id"]})
    assert response.status_code == 201
    assert response.json()["credit_card_id"] == card["id"]

    updated_card = client.get(f"/credit-cards/{card['id']}").json()
    assert updated_card["current_debt"] == 250
    assert updated_card["available_limit"] == 9750


def test_income_cannot_be_linked_to_a_card(client):
    card = _make_card(client)
    response = client.post("/transactions", json={"amount": 250, "type": "income", "credit_card_id": card["id"]})
    assert response.status_code == 400


def test_cannot_link_transaction_to_another_owners_card(make_authed_client):
    alice = make_authed_client(email="alice_link@example.com")
    bob = make_authed_client(email="bob_link@example.com")
    bob_card = _make_card(bob)

    response = alice.post("/transactions", json={"amount": 100, "type": "expense", "credit_card_id": bob_card["id"]})
    assert response.status_code == 404


def test_updating_linked_transaction_amount_adjusts_card_debt(client):
    card = _make_card(client)
    tx = client.post("/transactions", json={"amount": 100, "type": "expense", "credit_card_id": card["id"]}).json()

    client.put(f"/transactions/{tx['id']}", json={"amount": 300})

    assert client.get(f"/credit-cards/{card['id']}").json()["current_debt"] == 300


def test_moving_transaction_to_a_different_card_moves_the_debt(client):
    card_a = _make_card(client)
    card_b = _make_card(client)
    tx = client.post("/transactions", json={"amount": 100, "type": "expense", "credit_card_id": card_a["id"]}).json()

    client.put(f"/transactions/{tx['id']}", json={"credit_card_id": card_b["id"]})

    assert client.get(f"/credit-cards/{card_a['id']}").json()["current_debt"] == 0
    assert client.get(f"/credit-cards/{card_b['id']}").json()["current_debt"] == 100


def test_unlinking_transaction_decreases_card_debt(client):
    card = _make_card(client)
    tx = client.post("/transactions", json={"amount": 150, "type": "expense", "credit_card_id": card["id"]}).json()

    client.put(f"/transactions/{tx['id']}", json={"credit_card_id": None})

    assert client.get(f"/credit-cards/{card['id']}").json()["current_debt"] == 0


def test_changing_type_away_from_expense_while_linked_is_rejected(client):
    card = _make_card(client)
    tx = client.post("/transactions", json={"amount": 150, "type": "expense", "credit_card_id": card["id"]}).json()

    response = client.put(f"/transactions/{tx['id']}", json={"type": "income"})
    assert response.status_code == 400


def test_deleting_linked_transaction_decreases_card_debt(client):
    card = _make_card(client)
    tx = client.post("/transactions", json={"amount": 150, "type": "expense", "credit_card_id": card["id"]}).json()

    response = client.delete(f"/transactions/{tx['id']}")
    assert response.status_code == 204
    assert client.get(f"/credit-cards/{card['id']}").json()["current_debt"] == 0


def test_deleting_card_unlinks_but_keeps_its_transactions(client):
    card = _make_card(client)
    tx = client.post("/transactions", json={"amount": 150, "type": "expense", "credit_card_id": card["id"]}).json()

    response = client.delete(f"/credit-cards/{card['id']}")
    assert response.status_code == 204

    remaining = client.get(f"/transactions/{tx['id']}").json()
    assert remaining["credit_card_id"] is None
