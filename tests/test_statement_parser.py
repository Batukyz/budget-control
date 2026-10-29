import io
import pymupdf
import pytest
from datetime import date
from app.services.statement_parser import (
    guess_category,
    parse_turkish_amount,
    parse_turkish_date,
    detect_bank,
    extract_installment_info,
    parse_pdf_statement,
    build_statement_summary,
    classify_transaction_kind,
)


def test_guess_category():
    assert guess_category("MİGROS TİC. A.Ş. İSTANBUL")[0] == "Market"
    assert guess_category("SHELL PETROL A.S.")[0] == "Ulaşım & Akaryakıt"
    assert guess_category("YEMEKSEPETI ELEKTRONIK")[0] == "Yeme & İçme"
    assert guess_category("NETFLIX.COM")[0] == "Abonelikler"
    assert guess_category("SPOTIFY TURKEY")[0] == "Abonelikler"
    assert guess_category("TRENDYOL PAZARYERI")[0] == "Alışveriş & Giyim"
    assert guess_category("VATAN BILGISAYAR SAN")[0] == "Teknoloji & Elektronik"
    assert guess_category("KART BORCU ÖDEME - EFT")[0] == "Ödeme / Gelir"
    assert guess_category("BILINMEYEN DUKKAN XYZ")[0] == "Diğer"


def test_parse_turkish_amount():
    assert parse_turkish_amount("1.250,50 TL") == 1250.50
    assert parse_turkish_amount("450,00 TRY") == 450.00
    assert parse_turkish_amount("75,25 ₺") == 75.25
    assert parse_turkish_amount("-120,00") == -120.00
    assert parse_turkish_amount("120,00-") == -120.00
    assert parse_turkish_amount("12.450,90") == 12450.90
    assert parse_turkish_amount("50.00") == 50.00


def test_parse_turkish_date():
    assert parse_turkish_date("14.10.2026") == date(2026, 10, 14)
    assert parse_turkish_date("05/04/2026") == date(2026, 4, 5)
    assert parse_turkish_date("22-11-2026") == date(2026, 11, 22)
    assert parse_turkish_date("invalid") is None


def test_detect_bank():
    assert detect_bank("GARANTİ BBVA BONUS KART EKSTRESİ") == "Garanti BBVA"
    assert detect_bank("TÜRKİYE İŞ BANKASI MAXIMUM KART") == "Türkiye İş Bankası"
    assert detect_bank("YAPI VE KREDİ WORLDCARD HESAP ÖZETİ") == "Yapı Kredi"
    assert detect_bank("ENPARA.COM KREDİ KARTI EKSTRESİ") == "Enpara.com"
    assert detect_bank("AKBANK AXESS KART HESAP ÖZETİ") == "Akbank"


def test_extract_installment_info():
    assert extract_installment_info("MİGROS (1/6)") == "1/6"
    assert extract_installment_info("ZARA GIYIM 02/03") == "02/03"
    assert extract_installment_info("TEKNOSA 3. TAKSIT") == "3/Taksit"
    assert extract_installment_info("STARBUCKS COFFEE") is None


def test_parse_pdf_statement_in_memory():
    # Build a sample bank statement PDF in memory using pymupdf
    doc = pymupdf.open()
    page = doc.new_page()

    text_lines = [
        "GARANTİ BBVA BONUS HESAP ÖZETİ",
        "Dönem: 01.10.2026 - 31.10.2026",
        "İşlem Tarihi Açıklama Tutar",
        "05.10.2026 MIGROS TICARET A.S. 450,50 TL",
        "08.10.2026 SHELL PETROL ISTANBUL 850,00 TL",
        "12.10.2026 NETFLIX.COM (ABONELIK) 229,99 TL",
        "15.10.2026 TRENDYOL TEKSTIL (1/3) 1.200,00 TL",
        "20.10.2026 KART BORCU ÖDEME - EFT 2.000,00 TL (A)",
    ]

    y = 50
    for line in text_lines:
        page.insert_text((50, y), line, fontsize=11)
        y += 25

    pdf_bytes = doc.write()
    doc.close()

    result = parse_pdf_statement(pdf_bytes)

    assert result["bank_name"] == "Garanti BBVA"
    assert result["total_found"] == 5

    txs = result["transactions"]
    assert txs[0]["description"] == "MIGROS TICARET A.S."
    assert txs[0]["amount"] == 450.50
    assert txs[0]["type"] == "expense"
    assert txs[0]["suggested_category"] == "Market"

    assert txs[1]["suggested_category"] == "Ulaşım & Akaryakıt"
    assert txs[2]["suggested_category"] == "Abonelikler"
    assert txs[3]["installment_info"] == "1/3"
    assert txs[3]["suggested_category"] == "Alışveriş & Giyim"

    # Payment row
    assert txs[4]["type"] == "income"


def test_parse_pdf_statement_multiline_and_payment_processors():
    doc = pymupdf.open()
    page = doc.new_page()

    # Simulate complex statement rows:
    # 1. Payment processor expense (PAYTR ODEME / IYZICO / FATURA ODEME) must stay 'expense'
    # 2. Multi-line wrapped description (Date on line 1, Desc on line 2 & 3, Amount on line 4)
    # 3. Trailing bonus/points column after amount
    text_lines = [
        "YAPI VE KREDI WORLDCARD HESAP OZETI",
        "03.10.2026 PAYTR ODEME HIZMETLERI ISTANBUL 1.850,00 TL",
        "06.10.2026 IYZICO / AMAZON.COM.TR 2.400,00 TL 12,00 Puan",
        "09.10.2026 OTOMATIK FATURA ODEME TURKCELL 450,00 TL",
        "11.10.2026",
        "12.10.2026",
        "BOYNER BUYUK MAGAZACILIK",
        "ISTANBUL TR (2/6)",
        "1.750,00 TL",
    ]

    y = 40
    for line in text_lines:
        page.insert_text((45, y), line, fontsize=10)
        y += 22

    pdf_bytes = doc.write()
    doc.close()

    result = parse_pdf_statement(pdf_bytes)
    assert result["bank_name"] == "Yapı Kredi"
    assert result["total_found"] == 4

    txs = result["transactions"]
    # All 4 should be expenses, none misclassified as income!
    assert all(t["type"] == "expense" for t in txs)
    total_exp = sum(t["amount"] for t in txs)
    assert total_exp == pytest.approx(1850.0 + 2400.0 + 450.0 + 1750.0)
    assert txs[3]["installment_info"] == "2/6"


def test_turkish_date_formats_and_year_boundaries():
    assert parse_turkish_date("17/10/2026") == date(2026, 10, 17)
    assert parse_turkish_date("31.12.2025") == date(2025, 12, 31)
    assert parse_turkish_date("01/01/2026") == date(2026, 1, 1)
    assert parse_turkish_date("12/08/26") == date(2026, 8, 12)
    assert parse_turkish_date("15 Ekim 2026") == date(2026, 10, 15)
    assert parse_turkish_date("02 Ocak 2027") == date(2027, 1, 2)
    # Invalid calendar dates must return None rather than inventing a date
    assert parse_turkish_date("32/10/2026") is None
    assert parse_turkish_date("31/02/2026") is None


def test_uncertain_date_flagged_for_review():
    doc = pymupdf.open()
    page = doc.new_page()
    lines = [
        "QNB FINANSBANK KREDI KARTI HESAP OZETI",
        "17/10/2026 MIGROS TICARET A.S. ISTANBUL 450,00 TRY",
        "32/10/2026 SUPHELI TARIHLI HARCAMA ISTANBUL 210,00 TRY",
    ]
    y = 50
    for line in lines:
        page.insert_text((45, y), line, fontsize=10)
        y += 22
    pdf_bytes = doc.write()
    doc.close()

    result = parse_pdf_statement(pdf_bytes)
    assert result["total_found"] == 2
    valid_tx, invalid_date_tx = result["transactions"]
    assert valid_tx["occurred_on"] == "2026-10-17"
    assert valid_tx["raw_date"] == "17/10/2026"
    assert valid_tx["needs_review"] is False

    assert invalid_date_tx["occurred_on"] is None
    assert invalid_date_tx["raw_date"] == "32/10/2026"
    assert invalid_date_tx["needs_review"] is True
    assert any("tarih" in w.lower() for w in invalid_date_tx["warnings"])


def test_qnb_statement_regression_20_expenses_and_card_payment():
    """
    Verifies the QNB statement regression dataset:
    - 21 total transactions detected
    - 20 expense transactions totaling 9,745.19 TRY
    - 1 credit card payment (-11,753.03 TRY) excluded from expense total
    - Single-decimal QNB amounts (e.g., 1366,3 TRY, 630,0 TRY) and trailing installment/points columns
    - Repeated toll transactions (S/ICA YSS 3 KOPRU) preserved
    - Cross-month installment purchase date (12/08/2026) preserved accurately
    """
    qnb_lines = [
        "QNB FINANSBANK KREDI KARTI HESAP OZETI",
        "Kart Numarasi: 5342 **** **** 6441",
        "Hesap Kesim Tarihi: 29/10/2026",
        "Islem Tarihi Islem Aciklamasi Tutar Guncel/Toplam Taksit ParaPuan",
        "12/08/2026 CIB Taksitli HaliSaha ISTANBUL 1366,3 TRY 3/3,0 0,0",
        "17/10/2026 S/TRENDYOL PLUS ISTANBUL 75,0 TRY 0/0,0 0,0",
        "18/10/2026 BCC TOPLU YEMEK URETIM ISTANBUL 199,6 TRY 0/0,0 0,0",
        "19/10/2026 Odeme - Tesekkur Ederiz -11.753,03 TRY 0/0,0 0,0",
        "20/10/2026 BIM BIRLESIK MAGAZALAR ISTANBUL 209,0 TRY 0/0,0 0,0",
        "21/10/2026 S/GOOGLE *YouTubePremium 79,99 TRY 0/0,0 0,0",
        "22/10/2026 MIGROS TICARET A.S. ISTANBUL 542,75 TRY 0/0,0 0,0",
        "22/10/2026 SHELL PETROL A.S. ISTANBUL 1.250,0 TRY 0/0,0 0,0",
        "23/10/2026 EVE 1402 N MERKEZ AVM ISTANBUL 264,9 TRY 0/0,0 0,0",
        "23/10/2026 HAMIDIYE SEKERLEME ISTANBUL 180,0 TRY 0/0,0 0,0",
        "24/10/2026 NAK.VAS.V.D. ANKARA 1.485,5 TRY 0/0,0 0,0",
        "24/10/2026 S/AMAZON.COM.TR ISTANBUL 630,0 TRY 0/0,0 0,0",
        "25/10/2026 S/ICA YSS 3 KOPRU ISTANBUL 95,0 TRY 0/0,0 0,0",
        "25/10/2026 S/ICA YSS 3 KOPRU ISTANBUL 95,0 TRY 0/0,0 0,0",
        "25/10/2026 S/KARAYOLLARI OGS HGS ANKARA 350,0 TRY 0/0,0 0,0",
        "26/10/2026 STARBUCKS COFFEE ISTANBUL 202,5 TRY 0/0,0 0,0",
        "26/10/2026 YEMEKSEPETI ELEKTRONIK ISTANBUL 410,0 TRY 0/0,0 0,0",
        "27/10/2026 SOK MARKETLER TIC. A.S. ISTANBUL 319,65 TRY 0/0,0 0,0",
        "27/10/2026 ZARA TURKIYE ISTANBUL 1.190,0 TRY 0/0,0 0,0",
        "28/10/2026 ECZANE SAGLIK ISTANBUL 450,0 TRY 0/0,0 0,0",
        "28/10/2026 NETFLIX.COM ISTANBUL 350,0 TRY 0/0,0 0,0",
    ]

    doc = pymupdf.open()
    page = doc.new_page()
    y = 35
    for line in qnb_lines:
        page.insert_text((35, y), line, fontsize=9)
        y += 18
    pdf_bytes = doc.write()
    doc.close()

    result = parse_pdf_statement(pdf_bytes)
    assert result["bank_name"] == "QNB Finansbank"
    assert result["card_last4"] == "6441"
    assert result["total_found"] == 21
    assert result["expense_count"] == 20
    assert result["payment_count"] == 1
    assert result["refund_count"] == 0
    assert result["total_expenses"] == pytest.approx(9745.19)
    assert result["total_payments"] == pytest.approx(11753.03)
    assert result["signed_total_payments"] == pytest.approx(-11753.03)

    # Verify individual dates and classifications
    txs = result["transactions"]
    assert txs[0]["occurred_on"] == "2026-08-12"
    assert txs[0]["amount"] == pytest.approx(1366.30)
    assert txs[0]["transaction_kind"] == "expense"
    assert txs[0]["affects_expense_total"] is True

    payment_txs = [t for t in txs if t["transaction_kind"] == "credit_card_payment"]
    assert len(payment_txs) == 1
    assert payment_txs[0]["occurred_on"] == "2026-10-19"
    assert payment_txs[0]["amount"] == pytest.approx(11753.03)
    assert payment_txs[0]["signed_amount"] == pytest.approx(-11753.03)
    assert payment_txs[0]["affects_expense_total"] is False

    # Repeated toll charges on 25/10/2026 must both be preserved
    bridge_tolls = [t for t in txs if "ICA YSS 3 KOPRU" in t["description"]]
    assert len(bridge_tolls) == 2
    assert all(t["occurred_on"] == "2026-10-25" for t in bridge_tolls)
    assert all(t["suggested_category"] == "Ulaşım & Akaryakıt" for t in bridge_tolls)


def test_summary_recalculation_on_selection_and_edits():
    sample_txs = [
        {
            "amount": 500.0,
            "transaction_kind": "expense",
            "selected_by_default": True,
            "needs_review": False,
            "is_duplicate": False,
        },
        {
            "amount": 1200.0,
            "transaction_kind": "expense",
            "selected_by_default": True,
            "needs_review": False,
            "is_duplicate": False,
        },
        {
            "amount": 150.0,
            "transaction_kind": "refund",
            "selected_by_default": True,
            "needs_review": False,
            "is_duplicate": False,
        },
        {
            "amount": 3000.0,
            "transaction_kind": "credit_card_payment",
            "selected_by_default": True,
            "needs_review": False,
            "is_duplicate": False,
        },
    ]

    initial = build_statement_summary(sample_txs)
    assert initial["total_found"] == 4
    assert initial["selected_count"] == 4
    assert initial["excluded_count"] == 0
    assert initial["total_expenses"] == pytest.approx(1700.0)
    assert initial["total_refunds"] == pytest.approx(150.0)
    assert initial["total_payments"] == pytest.approx(3000.0)
    assert initial["net_movement"] == pytest.approx(1700.0 - 150.0 - 3000.0)

    # Deselect the 500 TRY expense -> total_expenses must decrease by 500 immediately
    sample_txs[0]["selected_by_default"] = False
    after_deselect = build_statement_summary(sample_txs)
    assert after_deselect["selected_count"] == 3
    assert after_deselect["excluded_count"] == 1
    assert after_deselect["total_expenses"] == pytest.approx(1200.0)

    # Re-select the 500 TRY expense and edit its amount to 650 TRY
    sample_txs[0]["selected_by_default"] = True
    sample_txs[0]["amount"] = 650.0
    after_reselect_and_edit = build_statement_summary(sample_txs)
    assert after_reselect_and_edit["selected_count"] == 4
    assert after_reselect_and_edit["total_expenses"] == pytest.approx(1850.0)


