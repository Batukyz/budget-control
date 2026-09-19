def test_account_reset_requires_auth(anon_client):
    res = anon_client.post("/account/reset")
    assert res.status_code == 401


def test_account_reset_wipes_financial_data_and_keeps_user(client):
    # 1. Populate various financial data
    card = client.post(
        "/credit-cards",
        json={"bank_name": "Garanti", "limit_amount": 10000, "statement_day": 1, "due_day": 10},
    ).json()

    client.post(
        "/installments",
        json={
            "credit_card_id": card["id"],
            "description": "Buzdolabı",
            "total_amount": 5000.0,
            "installment_count": 5,
        },
    )

    client.post(
        "/transactions",
        json={"amount": 150.0, "type": "expense", "category": "Gıda", "note": "Market alışverişi"},
    )

    client.post(
        "/subscriptions",
        json={"name": "Spotify", "amount": 59.99, "billing_cycle": "monthly", "next_due_date": "2026-10-01"},
    )

    client.post(
        "/recurring-transactions",
        json={"name": "Kira", "amount": 12000.0, "type": "expense", "frequency": "monthly", "next_due_date": "2026-10-01"},
    )

    client.post(
        "/categories",
        json={"name": "Özel Kategori", "type": "expense"},
    )

    client.post(
        "/budgets",
        json={"category": "Gıda", "monthly_limit": 3000.0},
    )

    # 2. Call reset
    reset_res = client.post("/account/reset")
    assert reset_res.status_code == 200
    assert "başarıyla sıfırlandı" in reset_res.json()["message"]

    # 3. Verify financial tables are completely clean
    assert len(client.get("/transactions").json()) == 0
    assert len(client.get("/credit-cards").json()) == 0
    assert len(client.get("/installments").json()) == 0
    assert len(client.get("/subscriptions").json()) == 0
    assert len(client.get("/recurring-transactions").json()) == 0
    assert len(client.get("/categories").json()) == 0
    assert len(client.get("/budgets").json()) == 0

    # 4. User is still authenticated and can create new records
    new_card = client.post(
        "/credit-cards",
        json={"bank_name": "İş Bankası", "limit_amount": 5000, "statement_day": 5, "due_day": 15},
    )
    assert new_card.status_code == 201


def test_account_reset_isolation_does_not_affect_other_users(make_authed_client):
    alice = make_authed_client(email="alice_reset@example.com")
    bob = make_authed_client(email="bob_reset@example.com")

    # Bob creates a card and transaction
    bob_card = bob.post(
        "/credit-cards",
        json={"bank_name": "Bob Bank", "limit_amount": 10000, "statement_day": 1, "due_day": 10},
    ).json()
    bob.post(
        "/transactions",
        json={"amount": 250.0, "type": "expense", "category": "Yemek"},
    )

    # Alice creates a card
    alice.post(
        "/credit-cards",
        json={"bank_name": "Alice Bank", "limit_amount": 20000, "statement_day": 5, "due_day": 15},
    )

    # Alice resets her account
    alice_reset = alice.post("/account/reset")
    assert alice_reset.status_code == 200

    # Alice has 0 cards
    assert len(alice.get("/credit-cards").json()) == 0

    # Bob's data remains 100% intact
    bob_cards = bob.get("/credit-cards").json()
    assert len(bob_cards) == 1
    assert bob_cards[0]["id"] == bob_card["id"]
    bob_txs = bob.get("/transactions").json()
    assert len(bob_txs) == 1
    assert bob_txs[0]["amount"] == 250.0
