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

