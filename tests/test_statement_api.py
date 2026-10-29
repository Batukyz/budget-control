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
