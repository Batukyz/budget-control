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


def test_account_reset_frontend_elements_and_modal_structure():
    import re
    from pathlib import Path

    html_path = Path("app/static/index.html")
    assert html_path.exists()
    content = html_path.read_text(encoding="utf-8")

    # Verify reset button and modal elements exist
    assert 'id="reset-account-btn"' in content
    assert 'id="confirm-modal-overlay"' in content
    assert 'id="confirm-modal-input"' in content
    assert 'id="confirm-modal-action"' in content
    assert 'SIFIRLA' in content

    # Verify div tags are balanced
    opens = len(re.findall(r"<div[\s>]", content, re.IGNORECASE))
    closes = len(re.findall(r"</div>", content, re.IGNORECASE))
    assert opens == closes, f"Unbalanced div tags in index.html: {opens} opens vs {closes} closes"

    # Verify confirm-modal-overlay is not nested inside category-modal-overlay
    cat_start = content.find('id="category-modal-overlay"')
    confirm_start = content.find('id="confirm-modal-overlay"')
    assert cat_start != -1 and confirm_start != -1

    cat_chunk = content[cat_start:confirm_start]
    cat_opens = len(re.findall(r"<div[\s>]", cat_chunk, re.IGNORECASE))
    cat_closes = len(re.findall(r"</div>", cat_chunk, re.IGNORECASE))
    assert cat_closes >= cat_opens, "confirm-modal-overlay is erroneously nested inside category-modal-overlay"


def test_ui_ux_enhancements_and_frontend_integrity(client):
    from pathlib import Path

    html_path = Path("app/static/index.html")
    content = html_path.read_text(encoding="utf-8")

    # 1. Auth & Password Visibility Toggles
    assert 'id="show-login"' in content
    assert 'class="password-toggle-btn"' in content
    assert 'data-toggle-password="login-password"' in content
    assert 'data-toggle-password="register-password"' in content
    assert 'data-toggle-password="account-password-input"' in content
    assert 'data-toggle-password="delete-account-password-input"' in content

    # 2. Dashboard Interactive Bento Metric Cards & Chart Controls
    assert 'id="topbar-status-pill"' in content
    assert 'id="cat-chart-type-expense"' in content
    assert 'id="cat-chart-type-income"' in content
    assert 'id="category-chart-subtitle"' in content
    assert 'id="open-plan-installment-btn"' in content
    assert "openInstallmentQuickAddModal" in content
    assert "bindMetricCardAction" in content
    assert "getSelectedOverviewMonthParam" in content

    # 3. Timezone-safe date parsing (no UTC date drift)
    assert 'new Date().toISOString().split("T")[0]' not in content
    assert "new Date(sub.next_due_date)" not in content
    assert "new Date(card.next_due_date)" not in content
    assert "new Date(p.due_date)" not in content

    # 4. Escape key closes all modals & palettes
    assert "closePayDebtModal();" in content
    assert "closeStatementModal()" in content
    assert "closeCmdPalette()" in content

    # 5. Category breakdown API supports month + type (expense & income) used by chart toggle
    client.post(
        "/transactions",
        json={"type": "expense", "amount": 450.0, "occurred_on": "2026-04-10", "category": "Market"},
    )
    client.post(
        "/transactions",
        json={"type": "income", "amount": 15000.0, "occurred_on": "2026-04-05", "category": "Maaş"},
    )

    exp_res = client.get("/reports/category-breakdown?month=2026-04&type=expense")
    assert exp_res.status_code == 200
    exp_data = exp_res.json()
    assert len(exp_data) == 1
    assert exp_data[0]["category"] == "Market"
    assert exp_data[0]["amount"] == 450.0

    inc_res = client.get("/reports/category-breakdown?month=2026-04&type=income")
    assert inc_res.status_code == 200
    inc_data = inc_res.json()
    assert len(inc_data) == 1
    assert inc_data[0]["category"] == "Maaş"
    assert inc_data[0]["amount"] == 15000.0

