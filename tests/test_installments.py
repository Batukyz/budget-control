from datetime import date, timedelta
import pytest


def _make_card(client, bank_name="Garanti BBVA", limit_amount=20000, current_debt=0):
    return client.post(
        "/credit-cards",
        json={
            "bank_name": bank_name,
            "limit_amount": limit_amount,
            "current_debt": current_debt,
            "statement_day": 15,
            "due_day": 25,
        },
    ).json()


def test_create_installment_plan_basic(client):
    card = _make_card(client)
    res = client.post(
        "/installments",
        json={
            "credit_card_id": card["id"],
            "description": "Telefon",
            "category": "Elektronik",
            "total_amount": 6000.0,
            "installment_count": 6,
            "first_due_date": "2026-09-20",
        },
    )
    assert res.status_code == 201
    plan = res.json()
    assert plan["id"] is not None
    assert plan["description"] == "Telefon"
    assert plan["total_amount"] == 6000.0
    assert plan["installment_count"] == 6
    assert len(plan["payments"]) == 6
    assert plan["paid_count"] == 0
    assert plan["paid_amount"] == 0.0
    assert plan["remaining_amount"] == 6000.0

    # Verify each payment schedule
    for i, p in enumerate(plan["payments"]):
        assert p["installment_number"] == i + 1
        assert p["amount"] == 1000.0
        assert p["status"] == "pending"

    # Card reflection
    card_info = client.get(f"/credit-cards/{card['id']}").json()
    assert card_info["total_installment_debt"] == 6000.0
    assert card_info["active_installment_count"] == 1


def test_deterministic_monetary_rounding_uneven_division(client):
    card = _make_card(client)
    # 10,000 / 3
    res = client.post(
        "/installments",
        json={
            "credit_card_id": card["id"],
            "description": "Bilgisayar Parçası",
            "total_amount": 10000.0,
            "installment_count": 3,
            "first_due_date": "2026-09-20",
        },
    )
    assert res.status_code == 201
    plan = res.json()
    amounts = [p["amount"] for p in plan["payments"]]
    assert amounts == [3333.33, 3333.33, 3333.34]
    assert round(sum(amounts), 2) == 10000.0


def test_month_end_date_calendar_progression(client):
    card = _make_card(client)
    # Starting Jan 31st -> Feb 28, Mar 31, Apr 30
    res = client.post(
        "/installments",
        json={
            "credit_card_id": card["id"],
            "description": "Mobilya",
            "total_amount": 4000.0,
            "installment_count": 4,
            "first_due_date": "2026-01-31",
        },
    )
    assert res.status_code == 201
    payments = res.json()["payments"]
    due_dates = [p["due_date"] for p in payments]
    assert due_dates == ["2026-01-31", "2026-02-28", "2026-03-31", "2026-04-30"]


def test_user_isolation(make_authed_client):
    alice = make_authed_client(email="alice_inst@example.com")
    bob = make_authed_client(email="bob_inst@example.com")

    alice_card = _make_card(alice, bank_name="Alice Bank")
    bob_card = _make_card(bob, bank_name="Bob Bank")

    # Bob cannot create an installment plan on Alice's card
    res = bob.post(
        "/installments",
        json={
            "credit_card_id": alice_card["id"],
            "description": "Hacked Plan",
            "total_amount": 1000.0,
            "installment_count": 2,
        },
    )
    assert res.status_code == 404

    # Alice creates a plan
    alice_plan = alice.post(
        "/installments",
        json={
            "credit_card_id": alice_card["id"],
            "description": "Alice Plan",
            "total_amount": 2000.0,
            "installment_count": 2,
        },
    ).json()

    # Bob cannot see Alice's plan
    assert bob.get(f"/installments/{alice_plan['id']}").status_code == 404
    bob_plans = bob.get("/installments").json()
    assert len(bob_plans) == 0


def test_pay_installment_payment_lifecycle_and_idempotency(client):
    card = _make_card(client, limit_amount=10000, current_debt=0)
    plan_res = client.post(
        "/installments",
        json={
            "credit_card_id": card["id"],
            "description": "Koltuk Takımı",
            "category": "Ev",
            "total_amount": 3000.0,
            "installment_count": 3,
            "first_due_date": "2026-09-20",
        },
    )
    plan = plan_res.json()
    pay1 = plan["payments"][0]
    pay2 = plan["payments"][1]
    pay3 = plan["payments"][2]

    # Initial card debt is 0, total installment debt is 3000
    c0 = client.get(f"/credit-cards/{card['id']}").json()
    assert c0["current_debt"] == 0.0
    assert c0["total_installment_debt"] == 3000.0

    # Pay 1st installment
    pay_res = client.post(f"/installments/{plan['id']}/payments/{pay1['id']}/pay")
    assert pay_res.status_code == 200
    pay_data = pay_res.json()
    assert pay_data["payment"]["status"] == "paid"
    assert pay_data["payment"]["paid_at"] is not None
    assert pay_data["transaction"]["id"] is not None
    assert pay_data["transaction"]["amount"] == 1000.0
    assert pay_data["transaction"]["credit_card_id"] == card["id"]
    assert pay_data["transaction"]["installment_plan_id"] == plan["id"]

    # Card current_debt increased by 1000, total installment debt remaining is 2000
    c1 = client.get(f"/credit-cards/{card['id']}").json()
    assert c1["current_debt"] == 1000.0
    assert c1["total_installment_debt"] == 2000.0

    # Activity contains the transaction
    tx_list = client.get("/transactions").json()
    assert len(tx_list) == 1
    assert tx_list[0]["installment_plan_id"] == plan["id"]
    assert "Koltuk Takımı" in tx_list[0]["note"]

    # Idempotency check: pay 1st installment again
    pay_again = client.post(f"/installments/{plan['id']}/payments/{pay1['id']}/pay")
    assert pay_again.status_code == 200
    # Current debt must not double count
    c1_again = client.get(f"/credit-cards/{card['id']}").json()
    assert c1_again["current_debt"] == 1000.0
    assert len(client.get("/transactions").json()) == 1

    # Pay 2nd and 3rd installments
    client.post(f"/installments/{plan['id']}/payments/{pay2['id']}/pay")
    client.post(f"/installments/{plan['id']}/payments/{pay3['id']}/pay")

    # Plan should now be completed
    updated_plan = client.get(f"/installments/{plan['id']}").json()
    assert updated_plan["status"] == "completed"
    assert updated_plan["paid_count"] == 3
    assert updated_plan["remaining_amount"] == 0.0

    c_final = client.get(f"/credit-cards/{card['id']}").json()
    assert c_final["current_debt"] == 3000.0
    assert c_final["total_installment_debt"] == 0.0
    assert c_final["active_installment_count"] == 0


def test_cannot_delete_credit_card_with_unpaid_installments(client):
    card = _make_card(client)
    client.post(
        "/installments",
        json={
            "credit_card_id": card["id"],
            "description": "Tablet",
            "total_amount": 5000.0,
            "installment_count": 5,
        },
    )

    # Deleting card should be rejected
    del_res = client.delete(f"/credit-cards/{card['id']}")
    assert del_res.status_code == 400
    assert "taksit" in del_res.json()["detail"].lower()

    # If we delete the installment plan first, card deletion succeeds
    plans = client.get("/installments").json()
    del_plan_res = client.delete(f"/installments/{plans[0]['id']}")
    assert del_plan_res.status_code == 204

    del_card_ok = client.delete(f"/credit-cards/{card['id']}")
    assert del_card_ok.status_code == 204


def test_installment_backup_export_and_import(client, make_authed_client):
    card = _make_card(client, bank_name="Yapı Kredi", limit_amount=15000)
    plan = client.post(
        "/installments",
        json={
            "credit_card_id": card["id"],
            "description": "Televizyon",
            "category": "Elektronik",
            "total_amount": 12000.0,
            "installment_count": 4,
            "first_due_date": "2026-10-01",
        },
    ).json()

    # Pay 1st installment
    client.post(f"/installments/{plan['id']}/payments/{plan['payments'][0]['id']}/pay")

    # Export backup
    backup = client.get("/account/export").json()
    assert len(backup["installment_plans"]) == 1
    assert len(backup["installment_payments"]) == 4
    assert backup["installment_plans"][0]["description"] == "Televizyon"

    # Import into another user
    other_user = make_authed_client(email="restore_user@example.com")
    import_res = other_user.post("/account/import", json=backup)
    assert import_res.status_code == 200
    assert import_res.json()["installment_plans"] == 1
    assert import_res.json()["installment_payments"] == 4

    # Verify restored plan
    restored_plans = other_user.get("/installments").json()
    assert len(restored_plans) == 1
    assert restored_plans[0]["description"] == "Televizyon"
    assert restored_plans[0]["paid_count"] == 1
    assert restored_plans[0]["remaining_amount"] == 9000.0


def test_installment_edge_cases_1_and_12(client):
    card = _make_card(client)
    # 1 installment
    res1 = client.post(
        "/installments",
        json={
            "credit_card_id": card["id"],
            "description": "Tek Çekim Taksit",
            "total_amount": 500.0,
            "installment_count": 1,
            "first_due_date": "2026-05-15",
        },
    )
    assert res1.status_code == 201
    plan1 = res1.json()
    assert plan1["installment_count"] == 1
    assert len(plan1["payments"]) == 1
    assert plan1["payments"][0]["amount"] == 500.0

    # 12 installments with leap year / cross-year calendar progression
    res12 = client.post(
        "/installments",
        json={
            "credit_card_id": card["id"],
            "description": "12 Ay Taksit",
            "total_amount": 12000.0,
            "installment_count": 12,
            "first_due_date": "2027-10-31",
        },
    )
    assert res12.status_code == 201
    plan12 = res12.json()
    assert len(plan12["payments"]) == 12
    # 2028 is a leap year -> Feb 2028 has 29 days!
    dates = [p["due_date"] for p in plan12["payments"]]
    assert dates[0] == "2027-10-31"
    assert dates[1] == "2027-11-30"
    assert dates[2] == "2027-12-31"
    assert dates[3] == "2028-01-31"
    assert dates[4] == "2028-02-29"  # leap year check
    assert dates[5] == "2028-03-31"
    assert dates[6] == "2028-04-30"
    assert dates[7] == "2028-05-31"
    assert dates[8] == "2028-06-30"
    assert dates[9] == "2028-07-31"
    assert dates[10] == "2028-08-31"
    assert dates[11] == "2028-09-30"


def test_frontend_elements_present():
    with open("app/static/index.html", "r", encoding="utf-8") as f:
        html = f.read()

    assert "id=\"reset-account-btn\"" in html
    assert "id=\"tab-installments\"" in html
    assert "id=\"wallet-installments-section\"" in html
    assert "id=\"installment-modal-overlay\"" in html
    assert "id=\"tx-installments\"" in html
    assert "id=\"confirm-modal-input\"" in html
    assert "SIFIRLA" in html

