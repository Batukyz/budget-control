import hashlib
import io
import json
import os
import re
from datetime import date, datetime
from typing import Optional
import pymupdf


def normalize_tr_lower(text: str) -> str:
    """Safely convert Turkish text to lowercase avoiding combining character artifacts."""
    if not text:
        return ""
    tr_map = str.maketrans({
        "İ": "i",
        "I": "ı",
        "Ğ": "ğ",
        "Ü": "ü",
        "Ş": "ş",
        "Ö": "ö",
        "Ç": "ç",
    })
    res = text.translate(tr_map).lower()
    return res.replace("i\u0307", "i")


def normalize_text_for_matching(text: str) -> str:
    """Normalize text by converting to lowercase and stripping Turkish diacritics for flexible fuzzy keyword matching."""
    s = normalize_tr_lower(text)
    ascii_map = str.maketrans({
        "ı": "i",
        "ğ": "g",
        "ü": "u",
        "ş": "s",
        "ö": "o",
        "ç": "c",
    })
    return s.translate(ascii_map)


CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "Abonelikler": [
        "trendyol plus", "hepsiburada premium", "amazon prime", "prime video",
        "youtube premium", "netflix", "spotify", "youtube", "icloud", "apple.com/bill",
        "itunes", "google play", "google storage", "google one", "disney", "blutv",
        "exxen", "gain", "chatgpt", "openai", "midjourney", "anthropic", "claude", "cursor",
        "github", "steam", "playstation", "psn", "xbox", "game pass", "deezer", "storytel",
        "patreon", "adobe", "canva", "microsoft 365",
    ],
    "Market": [
        "migros", "carrefour", "a101", "bim", "sok market", "şok market", "sok",
        "tarim kredi", "file market", "macrocenter", "şarküteri", "sarkuteri", "manav",
        "kasap", "fırın", "firin", "unlu mamul", "bakkal", "market", "peynirci",
        "happy center", "kim market", "onur market", "cagdas market", "metro market",
        "gida", "kuruyemis", "et ve sut", "hakmar", "mopas", "snowy", "ozdilek",
    ],
    "Yeme & İçme": [
        "trendyol yemek", "yemeksepeti", "getir yemek", "getir", "burger king", "mcdonalds",
        "starbucks", "kahve", "cafe", "restaurant", "restorant", "lokanta", "pide", "kebap",
        "döner", "doner", "börek", "borek", "pizza", "sushi", "tatlı", "tatli", "köfte", "kofte",
        "pastane", "meyhane", "bar", "pub", "meyve suyu", "lahmacun", "dürüm", "durum",
        "popeyes", "kfc", "dominos", "little caesars", "kahve dunyasi", "espresso",
        "simit", "tantuni", "kokorec", "ciger", "balik", "bufe", "kantin", "catering",
        "tavuk dunyasi", "hd iskender", "baydoner", "komagene", "arbys", "subway", "nero",
        "toplu yemek", "yemek uretim", "yemek", "sekerleme", "şekerleme", "pastanesi",
    ],
    "Ulaşım & Akaryakıt": [
        "shell", "opet", "bp", "petrol ofisi", "total", "aygaz", "tp petrol", "biletix",
        "obilet", "pegasus", "flypgs", "thy", "turkish air", "ajet", "anadolujet", "tcdd",
        "marmaray", "istanbulkart", "izmirimkart", "ankarakart", "otobüs", "otobus", "metro",
        "taksi", "uber", "bitaksi", "otopark", "ispark", "hgs", "ogs", "karayollari",
        "yolcu360", "rent a car", "akaryakit", "benzin", "otogaz", "lpg", "petrol",
        "marti", "binbin", "hop", "avrasya tuneli", "avrasya", "ido", "budo",
        "kopru", "köprü", "ica yss", "yss 3", "osmangazi", "otoyol", "kuzey marmara",
    ],
    "Faturalar": [
        "turkcell", "vodafone", "turk telekom", "turktelekom", "enerjisa", "başkent elektrik",
        "baskent elektrik", "ck bogazici", "gediz elektrik", "toroslar", "igdas", "aski",
        "iski", "izsu", "dogalgaz", "doğalgaz", "elektrik", "su faturasi", "turknet",
        "superonline", "millenicom", "d-smart", "digiturk", "tivibu", "fatura",
        "otomatik fatura", "fatura odeme", "kablonet", "aidat", "apartman", "site yonetim",
        "nak.vas", "vergi dairesi", "v.d.", "mtv",
    ],
    "Sağlık & Kozmetik": [
        "eczane", "optik", "hastane", "tıp merkezi", "tip merkezi", "gratis", "watsons",
        "sephora", "rossmann", "kozmetik", "diş", "dental", "klinik", "laboratuvar",
        "veteriner", "medikal", "acibadem", "memorial", "medical park", "liv hospital",
        "flormar", "mac cosmetics", "eve magaza", "eve 1", "yves rocher",
    ],
    "Teknoloji & Elektronik": [
        "vatan bilgisayar", "mediamarkt", "media markt", "teknosa", "itopya", "tebilon",
        "sinerji", "d&r", "dr.com", "monster notebook", "gaming", "bilgisayar", "elektronik",
        "apple store", "gürgençler", "gurgencler", "troy", "incehesap", "gamegaraj",
        "casper", "samsung", "xiaomi", "dyson", "philips",
    ],
    "Alışveriş & Giyim": [
        "trendyol", "hepsiburada", "hepsi burada", "amazon.com", "amazon com", "amazon tr",
        "n11", "online alisveris", "ciceksepeti", "pazarama", "pttavm", "zara", "bershka",
        "pull&bear", "pull and bear", "stradivarius", "massimo dutti", "mango", "h&m", "koton",
        "lc waikiki", "lcw", "mavi", "defacto", "boyner", "beymen", "decathlon", "nike",
        "adidas", "puma", "under armour", "flo", "skechers", "derimod", "vakko", "ipekyol",
        "network", "ikea", "koctas", "bauhaus", "tekzen", "english home", "madame coco",
        "karaca", "chakra", "penti", "altinyildiz", "kiğılı", "kigili", "us polo",
        "colins", "ltb", "jack & jones", "oysho", "calzedonia", "intimis", "sunglass",
        "merkez avm", "avm",
    ],
    "Eğitim": [
        "udemy", "coursera", "edx", "kitap", "kitapyurdu", "bkm kitap", "idefix",
        "üniversite", "universite", "kırtasiye", "kirtasiye", "okul", "kolej", "kurs",
        "akademi", "osym", "meb", "egitim", "dershane", "kres",
    ],
    "Eğlence & Sosyal": [
        "cinemapink", "paribu cineverse", "sinema", "tiyatro", "konser", "biletinial",
        "passo", "etkinlik", "müze", "muze", "lunapark", "bowling", "oyun", "spor salonu",
        "macfit", "fitness", "pilates", "otel", "hotel", "tatil", "ets tur", "jolly tur",
        "airbnb", "booking",
    ],
}

# Payment processor / POS prefixes that indicate an EXPENSE, never a card repayment
EXPENSE_PAYMENT_PROCESSORS = (
    "paytr", "iyzico", "iyzi ", "param", "sipay", "moka", "lidya",
    "birlesik odeme", "ozan", "papara", "ininal", "tosla", "upst",
    "mobil odeme", "fatura odeme", "otomatik odeme", "kurum odeme",
    "vergi odeme", "sgk odeme", "mtv odeme", "hgs odeme", "ogs odeme",
    "epin", "hepsipay", "trendyol pay", "moneypay", "pokus", "craftgate",
    "paratika", "paynet", "vallet", "paycell", "turkcell odeme", "vodafone odeme",
    "dgpara", "figopara", "weepay", "esnekpos", "bakiyem", "octopay", "paybull",
    "masterpass",
)

# Explicit phrases that mean a credit card debt payment (NOT an expense and NOT a merchant refund)
CARD_REPAYMENT_PATTERNS = (
    "kart borcu odeme", "kredi karti odeme", "kredi karti borc", "borc odeme", "hesaptan odeme",
    "eft ile odeme", "havale ile odeme", "internetten odeme", "mobil subeden odeme",
    "atm nakit odeme", "atmden odeme", "subeden odeme", "ekstre odemesi",
    "otomatik borc odeme", "nakit yatirma", "borc kapama", "kart odeme",
    "odeme - tesekkur", "odeme-tesekkur", "tesekkur ederiz",
    "odeme - eft", "odeme - havale", "odeme - hesaptan", "hesaptan kredi karti",
    "vadesiz hesaptan odeme", "enpara.com cep subesi odeme", "cep subesi odeme",
)

# Explicit phrases that mean a merchant refund / credit reversal
REFUND_PATTERNS = (
    "satis iadesi", "harcama iadesi", "iptal/iade", "iade islemi",
    "tutar iadesi", "ücret iadesi", "ucret iadesi", "ters kayit", "chargeback", "refund",
)

# Pre-compile normalized category keywords sorted by length descending so specific phrases match first
NORMALIZED_CATEGORY_PAIRS: list[tuple[str, str]] = sorted(
    [
        (normalize_text_for_matching(kw), cat)
        for cat, keywords in CATEGORY_KEYWORDS.items()
        for kw in keywords
    ],
    key=lambda pair: len(pair[0]),
    reverse=True,
)


def is_card_repayment(description: str) -> bool:
    """Return True only if description is a genuine credit card debt payment."""
    norm_desc = normalize_text_for_matching(description)
    if any(proc in norm_desc for proc in EXPENSE_PAYMENT_PROCESSORS):
        return False
    if any(pat in norm_desc for pat in CARD_REPAYMENT_PATTERNS):
        return True
    if re.search(r"deme\s*-\s*te\S*ekk\S*r\s+ederiz", description, re.IGNORECASE):
        return True
    if re.match(r"^(odeme|kredi karti odemesi|hesaptan aktarma)\b", norm_desc):
        return True
    return False


def is_merchant_refund(description: str) -> bool:
    """Return True if description explicitly indicates a merchant refund/reversal."""
    norm_desc = normalize_text_for_matching(description)
    if is_card_repayment(description):
        return False
    if any(pat in norm_desc for pat in REFUND_PATTERNS):
        return True
    if re.search(r"\b(iade|iptal)\b", norm_desc):
        return True
    return False


def is_card_repayment_or_refund(description: str) -> bool:
    """Return True if description is either a card debt repayment or a merchant refund."""
    return is_card_repayment(description) or is_merchant_refund(description)


def classify_transaction_kind(
    description: str,
    amt: float,
    is_alacak_sign: bool,
) -> str:
    """Classify transaction into 'expense', 'refund', or 'credit_card_payment'."""
    norm_desc = normalize_text_for_matching(description)
    is_expense_processor = any(proc in norm_desc for proc in EXPENSE_PAYMENT_PROCESSORS)

    if is_card_repayment(description):
        return "credit_card_payment"
    if is_merchant_refund(description):
        return "refund"
    if (is_alacak_sign or amt < 0) and not is_expense_processor:
        # Negative amount or Alacak sign on a non-payment-processor row:
        # Check if description looks like a payment or a merchant refund
        if "odeme" in norm_desc or "tesekkur" in norm_desc:
            return "credit_card_payment"
        return "refund"
    return "expense"


def guess_category(description: str, transaction_kind: str = "expense") -> tuple[str, float]:
    """Inspect description and suggest a high-confidence category based on Turkish keywords."""
    if transaction_kind == "credit_card_payment" or is_card_repayment(description):
        return "Ödeme / Gelir", 0.95
    if transaction_kind == "refund" or is_merchant_refund(description):
        return "İade / Alacak", 0.90

    norm_desc = normalize_text_for_matching(description)

    for kw_norm, cat in NORMALIZED_CATEGORY_PAIRS:
        if kw_norm in norm_desc:
            return cat, 0.85

    if any(p in norm_desc for p in EXPENSE_PAYMENT_PROCESSORS):
        return "Alışveriş & Giyim", 0.65

    return "Diğer", 0.30


def extract_merchant_name(description: str) -> str:
    """Extract a clean merchant identifier from a raw bank statement description."""
    if not description:
        return ""
    s = description.strip()
    # Remove leading 8-digit date stamp like "20260812 "
    s = re.sub(r"^\d{8}\s+", "", s)
    # Remove leading POS prefix like "S/" or "POS/"
    s = re.sub(r"^(?:S/|POS/|IZ\*|PAYTR\*|IYZI\s*\*?)\s*", "", s, flags=re.IGNORECASE)
    # Remove trailing installment text like "3. Taksit" or "(1/3)"
    s = re.sub(r"\s+(?:\(\d{1,2}/\d{1,2}\)|\d{1,2}\.\s*Taksit)\b.*$", "", s, flags=re.IGNORECASE)
    # Remove trailing city/country suffix like "İSTANBUL TRTR" or "ISTANBUL TR"
    s = re.sub(r"\s+(?:İSTANBUL|ISTANBUL|ANKARA|İZMİR|IZMIR)\s*(?:TR(?:TR)?)?$", "", s, flags=re.IGNORECASE)
    s = s.strip(" -·|")
    return s or description.strip()


def heal_split_numbers(text: str) -> str:
    """Heal numbers split by PDF kerning such as '1.250, 00', '1. 250,00', or '1 250,00'."""
    if not text:
        return ""
    s = re.sub(r"(\d)\s*,\s*(\d{1,2})(?!\d)", r"\1,\2", text)
    s = re.sub(r"(\b\d{1,3})\.\s+(\d{3},\d{1,2}\b)", r"\1.\2", s)
    s = re.sub(r"(?<![./\d])(\d{1,2})\s+(\d{3},\d{1,2})(?!\d)", r"\1.\2", s)
    s = re.sub(r"\b(\d{1,2})\s*([./])\s*(\d{1,2})\s*\2\s*(\d{2,4})\b", r"\1\2\3\2\4", s)
    return s


def parse_turkish_amount(amt_str: str) -> float:
    """Parse amounts like 1.250,50 or 1366,3 or 1250.50 or -45,00 or 1.250,00- or 1.500 TL."""
    cleaned = amt_str.replace("TL", "").replace("TRY", "").replace("₺", "").replace("USD", "").replace("EUR", "").strip()
    cleaned = re.sub(r"[\s\xa0]+", "", cleaned)

    is_negative = False
    if cleaned.startswith("-") or cleaned.endswith("-"):
        is_negative = True
        cleaned = cleaned.replace("-", "")
    if cleaned.startswith("+") or cleaned.endswith("+"):
        cleaned = cleaned.replace("+", "")

    if "," in cleaned and "." in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned and "." not in cleaned:
        cleaned = cleaned.replace(",", ".")
    elif "." in cleaned and "," not in cleaned:
        parts = cleaned.split(".")
        if len(parts) > 2 or (len(parts) == 2 and len(parts[1]) == 3):
            cleaned = cleaned.replace(".", "")

    val = float(cleaned)
    return -val if is_negative else val


TR_MONTH_MAP = {
    "oca": 1, "ocak": 1,
    "sub": 2, "subat": 2,
    "mar": 3, "mart": 3,
    "nis": 4, "nisan": 4,
    "may": 5, "mayis": 5,
    "haz": 6, "haziran": 6,
    "tem": 7, "temmuz": 7,
    "agu": 8, "agustos": 8,
    "eyl": 9, "eylul": 9,
    "eki": 10, "ekim": 10,
    "kas": 11, "kasim": 11,
    "ara": 12, "aralik": 12,
}


def parse_turkish_date(date_str: str, fallback_year: Optional[int] = None) -> Optional[date]:
    """Parse DD.MM.YYYY, DD/MM/YYYY, DD-MM-YYYY, DD.MM.YY, '12 Ekim 2026', or '12 Ekim'."""
    if not date_str:
        return None
    s = date_str.strip()
    m_txt = re.match(r"^(\d{1,2})\s+([A-Za-zÇĞİÖŞÜçğıöşü]+)(?:\s+(\d{2,4}))?$", s)
    if m_txt:
        try:
            d = int(m_txt.group(1))
            m_name = normalize_text_for_matching(m_txt.group(2))
            m = TR_MONTH_MAP.get(m_name) or TR_MONTH_MAP.get(m_name[:3])
            raw_y = m_txt.group(3)
            if not raw_y and fallback_year is None:
                return None
            y = int(raw_y) if raw_y else fallback_year
            if y < 100:
                y += 2000
            if m and 2000 <= y <= 2100:
                return date(y, m, d)
        except (ValueError, TypeError):
            return None

    cleaned = re.sub(r"\s+", "", s).replace("/", ".").replace("-", ".")
    parts = cleaned.split(".")
    if len(parts) != 3:
        return None
    try:
        d, m, y = int(parts[0]), int(parts[1]), int(parts[2])
        if y < 100:
            y += 2000
        if not (2000 <= y <= 2100):
            return None
        return date(y, m, d)
    except (ValueError, TypeError):
        return None


def detect_bank(text: str) -> str:
    """Identify the issuing bank from statement text."""
    t_norm = normalize_text_for_matching(text)
    if "garanti" in t_norm or "bonus" in t_norm:
        return "Garanti BBVA"
    if "is bankasi" in t_norm or "maximum" in t_norm:
        return "Türkiye İş Bankası"
    if "yapi kredi" in t_norm or "worldcard" in t_norm:
        return "Yapı Kredi"
    if "enpara" in t_norm:
        return "Enpara.com"
    if "qnb finansbank" in t_norm or "qnb" in t_norm or "cardfinans" in t_norm or "parapuan" in t_norm:
        return "QNB Finansbank"
    if "akbank" in t_norm or "axess" in t_norm or "wings" in t_norm:
        return "Akbank"
    if "ziraat" in t_norm or "bankkart" in t_norm:
        return "Ziraat Bankası"
    if "vakifbank" in t_norm:
        return "VakıfBank"
    if "halkbank" in t_norm or "paraf" in t_norm:
        return "Halkbank"
    if "kuveyt turk" in t_norm or "saglam kart" in t_norm:
        return "Kuveyt Türk"
    if "teb" in t_norm or "turk ekonomi bankasi" in t_norm:
        return "TEB"
    if "denizbank" in t_norm:
        return "DenizBank"
    return "Banka Ekstresi (Genel)"


def extract_statement_metadata(text: str) -> dict:
    """Extract card last 4 digits and statement date from header if available."""
    card_last4 = None
    m_card = re.search(r"son\s+4\s+hanesi\s+(\d{4})", text, re.IGNORECASE)
    if not m_card:
        m_card = re.search(
            r"(?:\d{4}|\*{4})[\s*-]+(?:\*{4}|x{4})[\s*-]+(?:\*{4}|x{4})[\s*-]+(\d{4})\b",
            text,
            re.IGNORECASE,
        )
    if m_card:
        card_last4 = m_card.group(1)

    stmt_date = None
    m_date = re.search(rf"({DATE_TOKEN_PATTERN})\s+tarihli", text, re.IGNORECASE)
    if not m_date:
        m_date = re.search(rf"hesap\s+kesim\s+tarihi\s*[:.]?\s*({DATE_TOKEN_PATTERN})", text, re.IGNORECASE)
    if m_date:
        stmt_date = parse_turkish_date(m_date.group(1))

    return {
        "card_last4": card_last4,
        "statement_date": stmt_date.isoformat() if stmt_date else None,
    }


def extract_installment_info(description: str) -> Optional[str]:
    """Detect installment tokens like 1/6, (02/12), 3/3,0, or 3. TAKSIT."""
    # Match (1/6) or 02/06 or QNB's 3/3,0 format, avoiding dates like 12/10/2026
    for match in re.finditer(r"(?<![./\d])\(?\b(\d{1,2})\s*/\s*(\d{1,2})(?:,0+)?\b\)?(?![./\d])", description):
        cur, tot = int(match.group(1)), int(match.group(2))
        if 1 <= cur <= tot <= 36 and tot > 1:
            return f"{match.group(1)}/{match.group(2)}"
    match_txt = re.search(r"\b(\d{1,2})\.\s*taksit\b", description, re.IGNORECASE)
    if match_txt:
        return f"{match_txt.group(1)}/Taksit"
    return None


SKIP_SUMMARY_KEYWORDS = (
    "hesap kesim", "son odeme tarihi", "donem borcu", "onceki donem borcu",
    "asgari odeme", "toplam borc", "kullanilabilir limit", "kart limiti",
    "nakit avans limiti", "devir bakiye", "gecen donem", "hesap ozeti toplam",
    "toplam puan", "kazanilan puan", "kalan taksit", "gelecek donem",
    "donem ici hareketler", "olan kartiniza ait", "son 4 hanesi",
    "yillik akdi faiz", "gecikme faiz", "musteri numarasi", "kart numarasi",
    "ekstre donemi", "toplam harcama", "bilgi amacli hazirlanmistir",
    "banka kayitlari esas",
)

DATE_TOKEN_PATTERN = r"(?:\d{1,2}[./-]\d{1,2}[./-]\d{2,4}|\d{1,2}\s+[A-Za-zÇĞİÖŞÜçğıöşü]{3,10}\s+\d{2,4})"
# Support 1 or 2 decimal digits after comma/dot (e.g. QNB's 1366,3 TRY and 630,0 TRY as well as 1.250,50)
AMOUNT_TOKEN_PATTERN = (
    r"[+-]?(?:"
    r"\d{1,3}(?:\.\d{3})+,\d{1,2}"
    r"|\d+,\d{1,2}"
    r"|\d{1,3}(?:,\d{3})+\.\d{1,2}"
    r"|\d+\.\d{1,2}"
    r"|\d{1,3}(?:\.\d{3})+(?=\s*(?:TL|TRY|₺|USD|EUR)\b)"
    r")[+-]?"
)
CARD_MASK_PREFIX_RE = re.compile(
    r"^(?:[*•\-]+|(?:\d{4}|\*{4})[\s*xX\d\-]{4,18})\s+",
    re.IGNORECASE,
)


def _reconstruct_block_rows(page) -> list[str]:
    """Reconstruct table rows from PDF text blocks, keeping multi-line cells intact and joining horizontal neighbors."""
    blocks = page.get_text("blocks")
    if not blocks:
        return []

    date_re = re.compile(DATE_TOKEN_PATTERN, re.IGNORECASE)
    cell_items: list[tuple[float, float, float, str]] = []

    for b in blocks:
        if len(b) >= 7 and b[6] != 0:
            continue
        x0, y0, x1, y1, text = b[0], b[1], b[2], b[3], b[4]
        raw_cell = text.strip()
        if not raw_cell:
            continue
        cell_lines = [ln.strip() for ln in raw_cell.splitlines() if ln.strip()]
        lines_with_dates = sum(1 for ln in cell_lines if date_re.search(heal_split_numbers(ln)))
        if lines_with_dates >= 2:
            step = max(1.0, (y1 - y0) / max(1, len(cell_lines)))
            for idx, ln in enumerate(cell_lines):
                ly0 = y0 + idx * step
                cell_items.append((ly0, ly0 + step, x0, heal_split_numbers(ln)))
        else:
            joined_cell = heal_split_numbers(" ".join(cell_lines))
            cell_items.append((y0, y1, x0, joined_cell))

    cell_items.sort(key=lambda c: ((c[0] + c[1]) / 2.0, c[2]))
    row_groups: list[tuple[float, float, list[tuple[float, str]]]] = []
    for y0, y1, x0, txt in cell_items:
        y_mid = (y0 + y1) / 2.0
        placed = False
        for idx, (ry0, ry1, items) in enumerate(row_groups):
            ry_mid = (ry0 + ry1) / 2.0
            overlap = min(y1, ry1) - max(y0, ry0)
            if abs(y_mid - ry_mid) <= 6.5 or overlap >= 3.0:
                items.append((x0, txt))
                row_groups[idx] = (min(ry0, y0), max(ry1, y1), items)
                placed = True
                break
        if not placed:
            row_groups.append((y0, y1, [(x0, txt)]))

    rows: list[str] = []
    for _, _, items in row_groups:
        items.sort(key=lambda it: it[0])
        row_str = heal_split_numbers(" ".join(it[1] for it in items).strip())
        if row_str:
            rows.append(row_str)
    return rows


def _reconstruct_horizontal_rows(page) -> list[str]:
    """Group PDF words by vertical Y coordinate and merge wrapped description/amount lines into parent date rows."""
    words = page.get_text("words")
    if not words:
        return []

    buckets: list[tuple[float, list[tuple[float, str]]]] = []
    for w in words:
        x0, y0, x1, y1, text = w[0], w[1], w[2], w[3], w[4]
        y_mid = (y0 + y1) / 2.0
        placed = False
        for idx, (b_y, items) in enumerate(buckets):
            if abs(b_y - y_mid) <= 4.5:
                items.append((x0, text))
                placed = True
                break
        if not placed:
            buckets.append((y_mid, [(x0, text)]))

    buckets.sort(key=lambda b: b[0])
    raw_rows: list[tuple[float, str]] = []
    for b_y, items in buckets:
        items.sort(key=lambda it: it[0])
        line_str = heal_split_numbers(" ".join(it[1] for it in items).strip())
        if line_str:
            raw_rows.append((b_y, line_str))

    date_any_re = re.compile(DATE_TOKEN_PATTERN, re.IGNORECASE)
    amt_search_re = re.compile(AMOUNT_TOKEN_PATTERN, re.IGNORECASE)

    merged_rows: list[str] = []
    last_date_y: Optional[float] = None
    pending_orphan_desc: Optional[tuple[float, str]] = None

    for b_y, line_str in raw_rows:
        cleaned_start = CARD_MASK_PREFIX_RE.sub("", line_str)
        starts_with_date = bool(re.match(rf"^({DATE_TOKEN_PATTERN})", cleaned_start, re.IGNORECASE))
        has_any_date = bool(date_any_re.search(line_str))
        has_amt = bool(amt_search_re.search(re.sub(rf"^{DATE_TOKEN_PATTERN}", "", cleaned_start)))

        if starts_with_date:
            if pending_orphan_desc is not None and (b_y - pending_orphan_desc[0]) <= 11.0:
                if _parse_single_candidate_line(line_str) is None:
                    dm = re.match(rf"^({DATE_TOKEN_PATTERN})\s*(.*)$", cleaned_start, re.IGNORECASE)
                    if dm:
                        line_str = f"{dm.group(1)} {pending_orphan_desc[1]} {dm.group(2)}".strip()
            pending_orphan_desc = None
            merged_rows.append(line_str)
            last_date_y = b_y
        elif merged_rows and last_date_y is not None and (b_y - last_date_y) <= 20.0 and not has_any_date:
            prev_line = merged_rows[-1]
            prev_parsed = _parse_single_candidate_line(prev_line)
            if prev_parsed is None:
                dm_prev = re.match(rf"^({DATE_TOKEN_PATTERN})\s+(.+)$", CARD_MASK_PREFIX_RE.sub("", prev_line), re.IGNORECASE)
                if dm_prev and not has_amt and amt_search_re.search(dm_prev.group(2)):
                    merged_rows[-1] = f"{dm_prev.group(1)} {line_str} {dm_prev.group(2)}"
                else:
                    merged_rows[-1] = f"{prev_line} {line_str}"
                last_date_y = b_y
            elif has_amt:
                merged_rows[-1] = f"{prev_line} {line_str}"
                last_date_y = b_y
            else:
                pending_orphan_desc = (b_y, line_str)
                merged_rows.append(line_str)
        else:
            if not has_any_date and not has_amt:
                pending_orphan_desc = (b_y, line_str)
            else:
                pending_orphan_desc = None
            merged_rows.append(line_str)

    return merged_rows


def _choose_best_amount_match(rest: str, amt_iter: list[re.Match]) -> re.Match:
    """Select the actual transaction amount when multiple amount-like numbers appear on a row."""
    if len(amt_iter) == 1:
        return amt_iter[0]

    has_installment = extract_installment_info(rest) is not None
    candidates = list(amt_iter)

    while len(candidates) >= 2:
        last_m = candidates[-1]
        prev_m = candidates[-2]
        after_last = rest[last_m.end():].strip().lower()
        between = rest[prev_m.end():last_m.start()].strip().lower()
        last_curr = (last_m.group(2) or "").upper()
        prev_curr = (prev_m.group(2) or "").upper()

        try:
            v_last = abs(parse_turkish_amount(last_m.group(1)))
            v_prev = abs(parse_turkish_amount(prev_m.group(1)))
        except ValueError:
            break

        # 1. If last column is 0,00 / 0,0 while previous is positive -> drop last
        if v_last == 0 and v_prev > 0:
            candidates.pop()
            continue

        # 2. If explicit bonus/point keywords appear near last_m -> drop last
        if any(p in after_last or p in between for p in ("puan", "bonus", "mil", "chip", "worldpuan", "maximiles", "parapuan")):
            candidates.pop()
            continue

        # 3. If prev_m has an explicit currency (TL/TRY/₺/USD/EUR) and last_m has NO currency (e.g. ParaPuan column) -> prefer prev_m
        if prev_curr in ("TL", "TRY", "₺", "USD", "EUR") and not last_curr:
            candidates.pop()
            continue

        # 4. If prev_m has TL/TRY/₺ and last_m has USD/EUR -> prefer TL
        if prev_curr in ("TL", "TRY", "₺") and last_curr in ("USD", "EUR"):
            candidates.pop()
            continue

        # 5. If last_m is a tiny fraction (< 12% of prev_m) and NOT a valid installment division of prev_m -> drop last
        if v_prev > 0 and v_last < v_prev * 0.12 and last_curr not in ("TL", "TRY", "₺"):
            is_installment_quotient = False
            if has_installment and v_last > 0:
                ratio = v_prev / v_last
                if 2 <= round(ratio) <= 36 and abs(ratio - round(ratio)) < 0.08:
                    is_installment_quotient = True
            if not is_installment_quotient:
                candidates.pop()
                continue

        break

    return candidates[-1]


def _parse_single_candidate_line(line: str, fallback_year: Optional[int] = None) -> Optional[dict]:
    """Attempt to extract a transaction from a single horizontal row string."""
    healed_line = heal_split_numbers(line.strip())
    cleaned_line = CARD_MASK_PREFIX_RE.sub("", healed_line)
    # Strip optional leading row index ONLY when followed by mandatory whitespace before the date
    cleaned_line = re.sub(rf"^\d{{1,3}}(?:\s*[-.)]\s*|\s+)(?={DATE_TOKEN_PATTERN})", "", cleaned_line)

    prefix_desc = ""
    date_match = re.match(
        rf"^({DATE_TOKEN_PATTERN})(?:\s+{DATE_TOKEN_PATTERN})?\s+(.+)$",
        cleaned_line,
        re.IGNORECASE,
    )
    if date_match:
        date_raw, rest = date_match.group(1), date_match.group(2).strip()
    else:
        any_date_m = re.search(
            rf"(?<![/\d])({DATE_TOKEN_PATTERN})(?:\s+{DATE_TOKEN_PATTERN})?\s+(.+)$",
            cleaned_line,
            re.IGNORECASE,
        )
        if not any_date_m:
            return None
        prefix_desc = cleaned_line[:any_date_m.start()].strip()
        prefix_desc = CARD_MASK_PREFIX_RE.sub("", prefix_desc).strip(" -·|*")
        date_raw = any_date_m.group(1)
        rest = any_date_m.group(2).strip()

    # Check if date needed fallback year or is a malformed date token so we can flag it for review
    date_needs_review = False
    tx_date = parse_turkish_date(date_raw, fallback_year=None)
    if tx_date is None and fallback_year is not None:
        tx_date = parse_turkish_date(date_raw, fallback_year=fallback_year)
        if tx_date is not None:
            date_needs_review = True
    if not tx_date:
        # Malformed date token (e.g. 32/10/2026 or 99.10.2026): flag for review instead of inventing a date
        date_needs_review = True

    # Find all currency amount tokens in the rest of the line, ignoring fractions like 0/0,0 or 3/3,0
    amt_iter = list(
        re.finditer(
            rf"(?<![/\d])({AMOUNT_TOKEN_PATTERN})\s*(TL|TRY|₺|USD|EUR)?\s*([+-]|(?:\(?[BAba]\)?)|Borç|Alacak)?(?=\s|$|[/*()])",
            rest,
            re.IGNORECASE,
        )
    )
    if not amt_iter:
        return None

    chosen_match = _choose_best_amount_match(rest, amt_iter)

    desc_end_idx = chosen_match.start()
    idx_in_iter = amt_iter.index(chosen_match)
    if idx_in_iter > 0:
        prev_m = amt_iter[idx_in_iter - 1]
        between_txt = rest[prev_m.end():chosen_match.start()].strip()
        if not between_txt or between_txt.upper() in ("TL", "TRY", "₺", "USD", "EUR", "-", "/"):
            desc_end_idx = prev_m.start()

    desc_before_amt = rest[:desc_end_idx].strip()
    after_amt = rest[chosen_match.end():].strip()

    desc_parts = [p for p in (prefix_desc, desc_before_amt) if p]
    if not desc_parts and after_amt:
        cleaned_after = re.sub(rf"^({AMOUNT_TOKEN_PATTERN})\s*(puan|bonus|mil|parapuan)?", "", after_amt, flags=re.IGNORECASE).strip()
        if cleaned_after:
            desc_parts.append(cleaned_after)

    raw_desc_joined = re.sub(r"\s+", " ", " ".join(desc_parts)).strip()
    desc_clean = raw_desc_joined.strip(" -·|")
    if len(desc_clean) < 2:
        return None

    norm_full = normalize_text_for_matching(f"{prefix_desc} {desc_clean}")
    if any(skip_kw in norm_full for skip_kw in SKIP_SUMMARY_KEYWORDS):
        return None

    amt_raw = chosen_match.group(1)
    curr_raw = (chosen_match.group(2) or "TRY").upper()
    if curr_raw in ("TL", "₺"):
        currency = "TRY"
    else:
        currency = curr_raw

    sign_raw = chosen_match.group(3) or ""
    prefix_slice = rest[max(0, chosen_match.start() - 3):chosen_match.start()]
    if "-" in prefix_slice and not amt_raw.startswith("-"):
        amt_raw = "-" + amt_raw
    elif "+" in prefix_slice and not amt_raw.startswith("+"):
        amt_raw = "+" + amt_raw

    try:
        amt = parse_turkish_amount(amt_raw)
    except ValueError:
        return None

    if amt == 0:
        return None

    is_alacak_sign = bool(
        (sign_raw and any(s in sign_raw.upper() for s in ("A", "+", "ALACAK")))
        or amt_raw.startswith("+")
        or amt_raw.endswith("+")
    )

    transaction_kind = classify_transaction_kind(desc_clean, amt, is_alacak_sign)
    category, conf = guess_category(desc_clean, transaction_kind=transaction_kind)

    final_amt = round(abs(amt), 2)
    if transaction_kind == "expense":
        tx_type = "expense"
        signed_amount = final_amt
        affects_expense_total = True
        suggested_cat = category
    elif transaction_kind == "credit_card_payment":
        tx_type = "income"
        signed_amount = -final_amt
        affects_expense_total = False
        suggested_cat = "Kredi Kartı Ödemesi"
    else:
        # refund
        tx_type = "income"
        signed_amount = -final_amt
        affects_expense_total = False
        suggested_cat = "İade / Alacak" if category == "Diğer" else category

    warnings: list[str] = []
    needs_review = False
    if tx_date is None:
        needs_review = True
        warnings.append("İşlem tarihi net olarak okunamadı, lütfen kontrol edin.")
    elif date_needs_review:
        needs_review = True
        warnings.append("İşlem tarihi yılı belgeden tahmin edildi, lütfen kontrol edin.")
    if transaction_kind == "expense" and conf < 0.5:
        needs_review = True
        warnings.append("Kategori otomatik belirlenemedi (Diğer), lütfen kontrol edin.")
    if transaction_kind == "refund" and not is_merchant_refund(desc_clean):
        needs_review = True
        warnings.append("Tutar negatif olduğu için iade olarak işaretlendi, lütfen kontrol edin.")

    inst_info = extract_installment_info(f"{desc_clean} {after_amt}")
    merchant = extract_merchant_name(desc_clean)
    iso_date = tx_date.isoformat() if tx_date else None

    return {
        "occurred_on": iso_date,
        "original_date": iso_date,
        "raw_date": date_raw,
        "merchant": merchant,
        "description": desc_clean,
        "original_description": raw_desc_joined or desc_clean,
        "amount": final_amt,
        "signed_amount": signed_amount,
        "currency": currency,
        "type": tx_type,
        "transaction_kind": transaction_kind,
        "affects_expense_total": affects_expense_total,
        "suggested_category": suggested_cat,
        "confidence": conf,
        "installment_info": inst_info,
        "needs_review": needs_review,
        "warnings": warnings,
        "is_duplicate": False,
        "duplicate_reason": None,
        "selected_by_default": True,
    }


def _extract_multiline_blocks(lines: list[str], fallback_year: Optional[int] = None) -> list[dict]:
    """Scan line sequences where Date, multi-line Description, and Amount may be split across 1 to 6 lines."""
    date_start_re = re.compile(
        rf"^(?:[*•\-]+|(?:\d{{4}}|\*{{4}})[\s*xX\d\-]{{4,18}})?\s*({DATE_TOKEN_PATTERN})(?:\s+{DATE_TOKEN_PATTERN})?\s*(.*)$",
        re.IGNORECASE,
    )
    date_only_re = re.compile(
        rf"^(?:[*•\-]+|(?:\d{{4}}|\*{{4}})[\s*xX\d\-]{{4,18}})?\s*({DATE_TOKEN_PATTERN})$",
        re.IGNORECASE,
    )

    results: list[dict] = []
    i = 0
    n = len(lines)
    last_unconsumed_desc: Optional[str] = None

    while i < n:
        line = heal_split_numbers(lines[i].strip())
        if not line:
            i += 1
            continue

        single = _parse_single_candidate_line(line, fallback_year=fallback_year)
        if single:
            results.append(single)
            last_unconsumed_desc = None
            i += 1
            continue

        dm = date_start_re.match(line)
        if dm:
            date_raw = dm.group(1)
            rem_first = dm.group(2).strip()
            tx_date = parse_turkish_date(date_raw, fallback_year=fallback_year)
            if tx_date:
                if rem_first and last_unconsumed_desc:
                    cand_with_prev = f"{date_raw} {last_unconsumed_desc} {rem_first}"
                    if i + 1 < n:
                        nxt = heal_split_numbers(lines[i + 1].strip())
                        if nxt and not date_start_re.match(nxt) and not _parse_single_candidate_line(nxt, fallback_year=fallback_year):
                            cand_with_prev_and_next = f"{date_raw} {last_unconsumed_desc} {nxt} {rem_first}"
                            parsed_both = _parse_single_candidate_line(cand_with_prev_and_next, fallback_year=fallback_year)
                            if parsed_both:
                                results.append(parsed_both)
                                last_unconsumed_desc = None
                                i += 2
                                continue
                    parsed_prev = _parse_single_candidate_line(cand_with_prev, fallback_year=fallback_year)
                    if parsed_prev:
                        results.append(parsed_prev)
                        last_unconsumed_desc = None
                        i += 1
                        continue

                desc_parts: list[str] = [rem_first] if rem_first else []
                j = i + 1
                matched_block = False
                while j < min(n, i + 8):
                    cand = heal_split_numbers(lines[j].strip())
                    if not cand:
                        j += 1
                        continue
                    if j == i + 1 and not desc_parts and date_only_re.match(cand):
                        j += 1
                        continue
                    if date_start_re.match(cand) or _parse_single_candidate_line(cand, fallback_year=fallback_year):
                        break

                    trial_parts = desc_parts + [cand]
                    combined_line = f"{date_raw} {' '.join(trial_parts)}"
                    parsed = _parse_single_candidate_line(combined_line, fallback_year=fallback_year)
                    if parsed:
                        # Peek ahead up to 2 lines for optional installment token (e.g. QNB's "3/3,0")
                        if j + 1 < n:
                            next_tok = lines[j + 1].strip()
                            inst = extract_installment_info(next_tok)
                            if inst and not parsed.get("installment_info"):
                                parsed["installment_info"] = inst
                        results.append(parsed)
                        last_unconsumed_desc = None
                        i = j + 1
                        matched_block = True
                        break
                    else:
                        if rem_first:
                            swapped_line = f"{date_raw} {cand} {rem_first}"
                            parsed_swapped = _parse_single_candidate_line(swapped_line, fallback_year=fallback_year)
                            if parsed_swapped:
                                results.append(parsed_swapped)
                                last_unconsumed_desc = None
                                i = j + 1
                                matched_block = True
                                break
                        desc_parts.append(cand)
                    j += 1

                if matched_block:
                    continue

        if not dm and len(line) >= 2:
            last_unconsumed_desc = line
        else:
            last_unconsumed_desc = None
        i += 1

    return results


def _merge_tx_lists(tx_lists: list[list[dict]]) -> list[dict]:
    """Select the highest-volume transaction list as primary and merge unique transactions from other strategies."""
    if not tx_lists:
        return []

    def _score(txs: list[dict]) -> tuple[int, float]:
        exp_sum = sum(t["amount"] for t in txs if t["transaction_kind"] == "expense")
        return (len(txs), round(exp_sum, 2))

    sorted_lists = sorted(tx_lists, key=_score, reverse=True)
    primary = sorted_lists[0]

    seen_counts: dict[tuple[str, float, str], int] = {}
    merged: list[dict] = []
    for tx in primary:
        key = (tx["occurred_on"], round(tx["amount"], 2), tx["transaction_kind"])
        seen_counts[key] = seen_counts.get(key, 0) + 1
        merged.append(tx)

    for secondary in sorted_lists[1:]:
        sec_counts: dict[tuple[str, float, str], int] = {}
        for tx in secondary:
            key = (tx["occurred_on"], round(tx["amount"], 2), tx["transaction_kind"])
            sec_counts[key] = sec_counts.get(key, 0) + 1
            if sec_counts[key] > seen_counts.get(key, 0):
                merged.append(tx)
                seen_counts[key] = sec_counts[key]

    return merged


def compute_statement_fingerprint(transactions: list[dict]) -> str:
    """Compute a deterministic fingerprint for the parsed statement transactions."""
    canonical_items = [
        {
            "d": t.get("occurred_on"),
            "a": round(float(t.get("amount", 0)), 2),
            "k": t.get("transaction_kind", t.get("type", "expense")),
            "m": normalize_text_for_matching(t.get("description", ""))[:40],
        }
        for t in transactions
    ]
    raw = json.dumps(canonical_items, sort_keys=True, separators=(",", ":"))
    return "stmt_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:55]


def build_statement_summary(transactions: list[dict]) -> dict:
    """Compute financial summary metrics separating expenses, refunds, and credit card payments."""
    total_found = len(transactions)
    selected_txs = [t for t in transactions if t.get("selected_by_default", True)]

    expense_txs = [t for t in selected_txs if t.get("transaction_kind") == "expense"]
    refund_txs = [t for t in selected_txs if t.get("transaction_kind") == "refund"]
    payment_txs = [t for t in selected_txs if t.get("transaction_kind") == "credit_card_payment"]

    total_expenses = round(sum(t["amount"] for t in expense_txs), 2)
    total_refunds = round(sum(t["amount"] for t in refund_txs), 2)
    total_payments = round(sum(t["amount"] for t in payment_txs), 2)
    net_movement = round(total_expenses - total_refunds - total_payments, 2)

    review_count = sum(1 for t in transactions if t.get("needs_review") or t.get("is_duplicate"))
    duplicate_count = sum(1 for t in transactions if t.get("is_duplicate"))

    return {
        "total_found": total_found,
        "selected_count": len(selected_txs),
        "excluded_count": total_found - len(selected_txs),
        "expense_count": len(expense_txs),
        "refund_count": len(refund_txs),
        "payment_count": len(payment_txs),
        "review_count": review_count,
        "duplicate_count": duplicate_count,
        "total_expenses": total_expenses,
        "total_refunds": total_refunds,
        "total_payments": total_payments,
        "signed_total_payments": round(-total_payments, 2) if total_payments > 0 else 0.0,
        "net_movement": net_movement,
    }


def parse_pdf_statement(file_bytes: bytes) -> dict:
    """Extract and parse credit card transactions from PDF statement bytes."""
    doc = pymupdf.open(stream=file_bytes, filetype="pdf")
    all_text = ""
    raw_lines: list[str] = []
    coord_lines: list[str] = []
    block_lines: list[str] = []

    for page in doc:
        page_text = page.get_text("text")
        all_text += page_text + "\n"
        for line in page_text.splitlines():
            stripped = line.strip()
            if stripped:
                raw_lines.append(stripped)
        coord_lines.extend(_reconstruct_horizontal_rows(page))
        block_lines.extend(_reconstruct_block_rows(page))

    bank_name = detect_bank(all_text)
    meta = extract_statement_metadata(all_text)

    # Infer fallback year from statement metadata if available
    fallback_year = 2026
    if meta.get("statement_date"):
        try:
            fallback_year = int(meta["statement_date"][:4])
        except (ValueError, TypeError):
            fallback_year = 2026

    raw_txs = _extract_multiline_blocks(raw_lines, fallback_year=fallback_year)
    coord_txs = _extract_multiline_blocks(coord_lines, fallback_year=fallback_year)
    block_txs = _extract_multiline_blocks(block_lines, fallback_year=fallback_year)

    merged = _merge_tx_lists([coord_txs, block_txs, raw_txs])

    for idx, tx in enumerate(merged):
        tx["row_id"] = idx

    summary = build_statement_summary(merged)
    fingerprint = compute_statement_fingerprint(merged)

    return {
        "bank_name": bank_name,
        "card_last4": meta.get("card_last4"),
        "statement_date": meta.get("statement_date"),
        "currency": merged[0]["currency"] if merged else "TRY",
        "statement_fingerprint": fingerprint,
        "already_imported_statement": False,
        **summary,
        "transactions": merged,
    }
