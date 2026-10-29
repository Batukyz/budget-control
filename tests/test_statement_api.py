import io
import pymupdf
import pytest
from datetime import date


def _make_dummy_statement_pdf() -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    lines = [
        "TÜRKİYE İŞ BANKASI MAXIMUM KART HESAP ÖZETİ",
        "Dönem: 01.10.2026 - 31.10.2026",
        "02.10.2026 CARREFOURSA MARKET 320,00 TL",
        "05.10.2026 SPOTIFY MUZIK 59,99 TL",
        "10.10.2026 BP PETROL 600,00 TL",
    ]
    y = 50
    for l in lines:
        page.insert_text((50, y), l, fontsize=11)
        y += 25
    b = doc.write()
    doc.close()
    return b


def test_parse_statement_pdf_requires_auth(anon_client):
    res = anon_client.post("/statements/parse-pdf", files={"file": ("ekstre.pdf", b"%PDF-dummy", "application/pdf")})
    assert res.status_code == 401


def test_parse_statement_pdf_rejects_non_pdf(client):
    res = client.post("/statements/parse-pdf", files={"file": ("test.txt", b"not a pdf", "text/plain")})
    assert res.status_code == 400


def test_parse_statement_pdf_success(client):
    pdf_bytes = _make_dummy_statement_pdf()
    res = client.post(
        "/statements/parse-pdf",
        files={"file": ("is_bankasi_ekstre.pdf", pdf_bytes, "application/pdf")},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["bank_name"] == "Türkiye İş Bankası"
    assert data["total_found"] == 3
    txs = data["transactions"]
    assert txs[0]["description"] == "CARREFOURSA MARKET"
    assert txs[0]["amount"] == 320.0
    assert txs[0]["type"] == "expense"
    assert txs[0]["suggested_category"] == "Market"
    assert txs[1]["suggested_category"] == "Abonelikler"
    assert txs[2]["suggested_category"] == "Ulaşım & Akaryakıt"


def test_confirm_statement_import(client):
    # 1. Create a credit card to link
    card_res = client.post(
        "/credit-cards",
        json={
            "bank_name": "İş Bankası",
            "card_name": "Maximum",
            "limit_amount": 25000,
            "statement_day": 15,
            "due_day": 25,
        },
    )
    assert card_res.status_code == 201
    card_id = card_res.json()["id"]

    # 2. Confirm import
    payload = {
        "credit_card_id": card_id,
        "transactions": [
            {
                "occurred_on": "2026-10-02",
                "description": "CARREFOURSA MARKET",
                "amount": 320.0,
                "type": "expense",
                "category": "Market",
            },
            {
                "occurred_on": "2026-10-05",
                "description": "SPOTIFY MUZIK",
                "amount": 59.99,
                "type": "expense",
                "category": "Abonelikler",
            },
            {
                "occurred_on": "2026-10-15",
                "description": "KART ODEME - HAVALE",
                "amount": 1000.0,
                "type": "income",
                "category": "Gelir",
            },
        ],
    }

    res = client.post("/statements/confirm-import", json=payload)
    assert res.status_code == 200
    body = res.json()
    assert body["imported_count"] == 3
    assert body["total_expense"] == 379.99
    assert body["total_income"] == 1000.0
    assert body["credit_card_id"] == card_id

    # 3. Verify transactions appear in list
    txs_res = client.get("/transactions")
    assert txs_res.status_code == 200
    notes = [t["note"] for t in txs_res.json()]
    assert "CARREFOURSA MARKET" in notes
    assert "SPOTIFY MUZIK" in notes


def test_parse_does_not_persist_and_cancel_leaves_db_unchanged(client):
    """
    Parsing a PDF must not write any transaction to the database.
    If the user cancels the review screen (never calls confirm-import), existing records remain untouched.
    """
    before_res = client.get("/transactions")
    assert before_res.status_code == 200
    before_ids = [t["id"] for t in before_res.json()]

    pdf_bytes = _make_dummy_statement_pdf()
    parse_res = client.post(
        "/statements/parse-pdf",
        files={"file": ("is_bankasi_ekstre.pdf", pdf_bytes, "application/pdf")},
    )
    assert parse_res.status_code == 200
    assert parse_res.json()["total_found"] == 3

    after_res = client.get("/transactions")
    assert after_res.status_code == 200
    after_ids = [t["id"] for t in after_res.json()]
    assert after_ids == before_ids


def test_import_selected_with_edited_fields_and_exact_pdf_dates(client):
    """
    Verifies:
    - Only selected transactions are imported (excluded/removed rows are omitted from confirm payload)
    - Manually edited date, description, amount, and category are persisted
    - Original PDF dates (including prior months like 2026-08-12 and 2026-10-17) are stored without timezone shift
    - Credit card payment is excluded from total_expense and dashboard month_expense
    - Dashboard (/overview and /reports/category-breakdown) reflects imported transactions immediately
    """
    doc = pymupdf.open()
    page = doc.new_page()
    lines = [
        "QNB FINANSBANK KREDI KARTI HESAP OZETI",
        "12/08/2026 CIB Taksitli HaliSaha ISTANBUL 1366,3 TRY 3/3,0 0,0",
        "17/10/2026 S/TRENDYOL PLUS ISTANBUL 75,0 TRY 0/0,0 0,0",
        "19/10/2026 Odeme - Tesekkur Ederiz -11.753,03 TRY 0/0,0 0,0",
        "22/10/2026 MIGROS TICARET A.S. ISTANBUL 542,75 TRY 0/0,0 0,0",
    ]
    y = 50
    for line in lines:
        page.insert_text((40, y), line, fontsize=10)
        y += 22
    pdf_bytes = doc.write()
    doc.close()

    parse_res = client.post(
        "/statements/parse-pdf",
        files={"file": ("qnb_ekstre.pdf", pdf_bytes, "application/pdf")},
    )
    assert parse_res.status_code == 200
    parsed = parse_res.json()
    assert parsed["total_found"] == 4
    assert parsed["expense_count"] == 3
    assert parsed["payment_count"] == 1
    assert parsed["total_expenses"] == pytest.approx(1366.30 + 75.00 + 542.75)

    # Simulate user review:
    # - Keep row 0 (12/08/2026, 1366.30 TRY) with original PDF date
    # - Edit row 1 (17/10/2026): change description, amount (75 -> 89.90), and category
    # - Include row 2 (Credit card payment -11,753.03 TRY) as credit_card_payment to verify it never inflates expenses
    # - Deselect/exclude row 3 (MIGROS 542.75 TRY)
    confirm_payload = {
        "statement_fingerprint": parsed["statement_fingerprint"],
        "transactions": [
            {
                "occurred_on": parsed["transactions"][0]["occurred_on"],  # "2026-08-12"
                "description": parsed["transactions"][0]["description"],
                "original_description": parsed["transactions"][0]["original_description"],
                "original_date": parsed["transactions"][0]["original_date"],
                "amount": parsed["transactions"][0]["amount"],
                "currency": "TRY",
                "type": "expense",
                "transaction_kind": "expense",
                "category": "Eğlence",
            },
            {
                "occurred_on": "2026-10-17",
                "description": "TRENDYOL PLUS YILLIK PLAN (DUZENLENDI)",
                "original_description": parsed["transactions"][1]["original_description"],
                "original_date": parsed["transactions"][1]["original_date"],
                "amount": 89.90,
                "currency": "TRY",
                "type": "expense",
                "transaction_kind": "expense",
                "category": "Abonelikler",
            },
            {
                "occurred_on": "2026-10-19",
                "description": parsed["transactions"][2]["description"],
                "original_description": parsed["transactions"][2]["original_description"],
                "original_date": parsed["transactions"][2]["original_date"],
                "amount": parsed["transactions"][2]["amount"],
                "currency": "TRY",
                "type": "income",
                "transaction_kind": "credit_card_payment",
                "category": "Ödeme / Gelir",
            },
        ],
    }

    confirm_res = client.post("/statements/confirm-import", json=confirm_payload)
    assert confirm_res.status_code == 200
    body = confirm_res.json()
    assert body["imported_count"] == 3
    # Total expense must only sum the 2 expenses (1366.30 + 89.90 = 1456.20), excluding the credit card payment!
    assert body["total_expense"] == pytest.approx(1456.20)
    assert body["total_payment"] == pytest.approx(11753.03)
    assert body["total_refund"] == 0.0

    # Verify stored dates and edited values in /transactions
    all_txs = client.get("/transactions").json()
    by_note = {t["note"]: t for t in all_txs}

    # Excluded MIGROS row must not be in DB
    assert not any("MIGROS" in (t["note"] or "") for t in all_txs)

    # Edited Trendyol row must have exact date 2026-10-17 and edited amount 89.90
    edited_tx = by_note["TRENDYOL PLUS YILLIK PLAN (DUZENLENDI)"]
    assert edited_tx["occurred_on"] == "2026-10-17"
    assert edited_tx["amount"] == pytest.approx(89.90)
    assert edited_tx["category"] == "Abonelikler"

    # Cross-month August installment must have exact date 2026-08-12
    aug_tx = next(t for t in all_txs if "HaliSaha" in (t["note"] or ""))
    assert aug_tx["occurred_on"] == "2026-08-12"
    assert aug_tx["amount"] == pytest.approx(1366.30)

    # Verify dashboard /overview and /reports/category-breakdown for October 2026
    overview_oct = client.get("/overview?month=2026-10").json()
    assert overview_oct["month_expense"] >= 89.90

    breakdown_oct = client.get("/reports/category-breakdown?month=2026-10").json()
    categories_oct = {item["category"]: item["amount"] for item in breakdown_oct}
    assert categories_oct.get("Abonelikler", 0) >= 89.90


def test_duplicate_prevention_and_legitimate_repeated_tolls(client):
    """
    Verifies:
    1. Legitimate repeated purchases/tolls on the same day (e.g. two S/ICA YSS 3 KOPRU 95,0 TRY on 25/10/2026)
       are BOTH imported when confirmed together in a statement.
    2. Importing the exact same statement a second time flags the rows as duplicates in parse-pdf
       and skips them in confirm-import unless force_duplicate=True.
    """
    doc = pymupdf.open()
    page = doc.new_page()
    lines = [
        "QNB FINANSBANK KREDI KARTI HESAP OZETI",
        "25/10/2026 S/ICA YSS 3 KOPRU ISTANBUL 95,0 TRY 0/0,0 0,0",
        "25/10/2026 S/ICA YSS 3 KOPRU ISTANBUL 95,0 TRY 0/0,0 0,0",
        "25/10/2026 S/KARAYOLLARI OGS HGS ANKARA 350,0 TRY 0/0,0 0,0",
    ]
    y = 50
    for line in lines:
        page.insert_text((40, y), line, fontsize=10)
        y += 22
    pdf_bytes = doc.write()
    doc.close()

    # First parse
    parse_res1 = client.post(
        "/statements/parse-pdf",
        files={"file": ("tolls.pdf", pdf_bytes, "application/pdf")},
    )
    assert parse_res1.status_code == 200
    data1 = parse_res1.json()
    assert data1["total_found"] == 3
    assert data1["already_imported_statement"] is False
    # Both bridge tolls must be selected by default so legitimate repeated tolls are preserved
    assert all(t["selected_by_default"] is True for t in data1["transactions"])

    # First confirm -> all 3 transactions must be imported
    confirm_payload = {
        "statement_fingerprint": data1["statement_fingerprint"],
        "transactions": [
            {
                "occurred_on": t["occurred_on"],
                "description": t["description"],
                "original_description": t["original_description"],
                "original_date": t["original_date"],
                "amount": t["amount"],
                "currency": t["currency"],
                "type": t["type"],
                "transaction_kind": t["transaction_kind"],
                "category": t["suggested_category"],
            }
            for t in data1["transactions"]
        ],
    }
    confirm_res1 = client.post("/statements/confirm-import", json=confirm_payload)
    assert confirm_res1.status_code == 200
    body1 = confirm_res1.json()
    assert body1["imported_count"] == 3
    assert body1["skipped_duplicates"] == 0
    assert body1["total_expense"] == pytest.approx(95.0 + 95.0 + 350.0)

    # Second parse of the exact same PDF -> must detect statement & row duplicates
    parse_res2 = client.post(
        "/statements/parse-pdf",
        files={"file": ("tolls.pdf", pdf_bytes, "application/pdf")},
    )
    assert parse_res2.status_code == 200
    data2 = parse_res2.json()
    assert data2["already_imported_statement"] is True
    assert all(t["is_duplicate"] is True for t in data2["transactions"])
    assert all(t["selected_by_default"] is False for t in data2["transactions"])

    # Second confirm without force_duplicate -> must skip all 3 duplicates
    confirm_res2 = client.post("/statements/confirm-import", json=confirm_payload)
    assert confirm_res2.status_code == 200
    body2 = confirm_res2.json()
    assert body2["imported_count"] == 0
    assert body2["skipped_duplicates"] == 3

