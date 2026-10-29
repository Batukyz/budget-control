import io
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
    "Market": [
        "migros", "carrefour", "a101", "bim", "sok market", "şok market", "sok",
        "tarim kredi", "file market", "macrocenter", "şarküteri", "sarkuteri", "manav",
        "kasap", "fırın", "firin", "unlu mamul", "bakkal", "market", "peynirci",
        "happy center", "kim market", "onur market", "cagdas market", "metro market",
        "gida", "kuruyemis", "kasap", "et ve sut"
    ],
    "Yeme & İçme": [
        "yemeksepeti", "getir", "trendyol yemek", "burger king", "mcdonalds", "starbucks",
        "kahve", "cafe", "restaurant", "restorant", "lokanta", "pide", "kebap", "döner",
        "doner", "börek", "borek", "pizza", "sushi", "tatlı", "tatli", "köfte", "kofte",
        "pastane", "meyhane", "bar", "pub", "meyve suyu", "lahmacun", "dürüm", "durum",
        "popeyes", "kfc", "dominos", "little caesars", "kahve dunyasi", "espresso",
        "simit", "tantuni", "kokorec", "ciger", "balik", "bufe", "kantin", "catering"
    ],
    "Ulaşım & Akaryakıt": [
        "shell", "opet", "bp", "petrol ofisi", "total", "aygaz", "tp petrol", "biletix",
        "obilet", "pegasus", "flypgs", "thy", "turkish air", "ajet", "anadolujet", "tcdd",
        "marmaray", "istanbulkart", "izmirimkart", "ankarakart", "otobüs", "otobus", "metro",
        "taksi", "uber", "bitaksi", "otopark", "ispark", "hgs", "ogs", "karayollari",
        "yolcu360", "rent a car", "akaryakit", "benzin", "otogaz", "lpg", "petrol",
        "marti", "binbin", "hop", "avrasya tuneli", "ido", "budo"
    ],
    "Abonelikler": [
        "netflix", "spotify", "youtube", "icloud", "apple.com/bill", "itunes", "google play",
        "google storage", "google one", "amazon prime", "prime video", "disney", "blutv",
        "exxen", "gain", "chatgpt", "openai", "midjourney", "anthropic", "claude", "cursor",
        "github", "steam", "playstation", "psn", "xbox", "game pass", "deezer", "storytel",
        "patreon", "adobe", "canva", "microsoft 365"
    ],
    "Faturalar": [
        "turkcell", "vodafone", "turk telekom", "turktelekom", "enerjisa", "başkent elektrik",
        "baskent elektrik", "ck bogazici", "gediz elektrik", "toroslar", "igdas", "aski",
        "iski", "izsu", "dogalgaz", "doğalgaz", "elektrik", "su faturasi", "turknet",
        "superonline", "millenicom", "d-smart", "digiturk", "tivibu", "fatura",
        "otomatik fatura", "fatura odeme", "kablonet", "aidat", "apartman", "site yonetim"
    ],
    "Alışveriş & Giyim": [
        "trendyol", "hepsiburada", "hepsi burada", "amazon.com", "amazon com", "amazon tr",
        "n11", "ciceksepeti", "pazarama", "pttavm", "zara", "bershka", "pull&bear",
        "pull and bear", "stradivarius", "massimo dutti", "mango", "h&m", "koton",
        "lc waikiki", "lcw", "mavi", "defacto", "boyner", "beymen", "decathlon", "nike",
        "adidas", "puma", "under armour", "flo", "skechers", "derimod", "vakko", "ipekyol",
        "network", "ikea", "koctas", "bauhaus", "tekzen", "english home", "madame coco",
        "karaca", "chakra", "penti", "altinyildiz", "kiğılı", "kigili", "us polo",
        "colins", "ltb", "jack & jones", "oysho", "calzedonia", "intimis", "sunglass"
    ],
    "Teknoloji & Elektronik": [
        "vatan bilgisayar", "mediamarkt", "media markt", "teknosa", "itopya", "tebilon",
        "sinerji", "d&r", "dr.com", "monster notebook", "gaming", "bilgisayar", "elektronik",
        "apple store", "gürgençler", "gurgencler", "troy", "incehesap", "gamegaraj",
        "casper", "samsung", "xiaomi", "dyson", "philips"
    ],
    "Sağlık & Kozmetik": [
        "eczane", "optik", "hastane", "tıp merkezi", "tip merkezi", "gratis", "watsons",
        "sephora", "rossmann", "kozmetik", "diş", "dental", "klinik", "laboratuvar",
        "veteriner", "medikal", "acibadem", "memorial", "medical park", "liv hospital",
        "flormar", "mac cosmetics", "eve magaza", " Yves rocher", "yves rocher"
    ],
    "Eğitim": [
        "udemy", "coursera", "edx", "kitap", "kitapyurdu", "bkm kitap", "idefix",
        "üniversite", "universite", "kırtasiye", "kirtasiye", "okul", "kolej", "kurs",
        "akademi", "osym", "meb", "egitim", "dershane", "kres"
    ],
    "Eğlence & Sosyal": [
        "cinemapink", "paribu cineverse", "sinema", "tiyatro", "konser", "biletinial",
        "passo", "etkinlik", "müze", "muze", "lunapark", "bowling", "oyun", "spor salonu",
        "macfit", "fitness", "pilates", "otel", "hotel", "tatil", "ets tur", "jolly tur",
        "airbnb", "booking"
    ],
}

# Payment processor / POS prefixes that indicate an EXPENSE, never a card repayment
EXPENSE_PAYMENT_PROCESSORS = (
    "paytr", "iyzico", "iyzi ", "param", "sipay", "moka", "lidya",
    "birlesik odeme", "ozan", "papara", "ininal", "tosla", "upst",
    "mobil odeme", "fatura odeme", "otomatik odeme", "kurum odeme",
    "vergi odeme", "sgk odeme", "mtv odeme", "hgs odeme", "ogs odeme",
    "epin", "hepsipay", "trendyol pay", "moneypay", "pokus", "craftgate",
)

# Explicit phrases that mean a credit card debt payment or merchant refund (INCOME / ALACAK)
CARD_REPAYMENT_PATTERNS = (
    "kart borcu odeme", "kredi karti odeme", "borc odeme", "hesaptan odeme",
    "eft ile odeme", "havale ile odeme", "internetten odeme", "mobil subeden odeme",
    "atm nakit odeme", "atmden odeme", "subeden odeme", "ekstre odemesi",
    "otomatik borc odeme", "nakit yatirma", "borc kapama", "kart odeme",
    "odeme - tesekkurler", "odeme-tesekkurler", "tesekkur ederiz",
    "odeme - eft", "odeme - havale", "odeme - hesaptan", "iade",
    "satis iadesi", "harcama iadesi", "iptal/iade",
)

# Pre-compile normalized category keywords
NORMALIZED_CATEGORY_KEYWORDS = {
    cat: [normalize_text_for_matching(kw) for kw in keywords]
    for cat, keywords in CATEGORY_KEYWORDS.items()
}


def is_card_repayment_or_refund(description: str) -> bool:
    """Return True only if description is a genuine card debt repayment or merchant refund."""
    norm_desc = normalize_text_for_matching(description)
    # If it contains a known payment processor / bill payment phrase, it is an EXPENSE
    if any(proc in norm_desc for proc in EXPENSE_PAYMENT_PROCESSORS):
        return False
    # Check explicit card repayment / refund patterns
    if any(pat in norm_desc for pat in CARD_REPAYMENT_PATTERNS):
        return True
    # Standalone "odeme" or "alacak" when the whole description is just a bank payment line
    if re.match(r"^(odeme|kredi karti odemesi|hesaptan aktarma|alacak)\b", norm_desc):
        return True
    return False


def guess_category(description: str) -> tuple[str, float]:
    """Inspect description and suggest a high-confidence category based on Turkish keywords."""
    if is_card_repayment_or_refund(description):
        return "Ödeme / Gelir", 0.95

    norm_desc = normalize_text_for_matching(description)

    for cat, keywords in NORMALIZED_CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw in norm_desc:
                return cat, 0.85

    # If it uses an online payment processor like PayTR / İyzico / Param, default to Alışveriş & Giyim
    if any(p in norm_desc for p in ("paytr", "iyzico", "iyzi ", "param", "sipay", "moka", "lidya", "hepsipay")):
        return "Alışveriş & Giyim", 0.65

    return "Diğer", 0.30


def parse_turkish_amount(amt_str: str) -> float:
    """Parse amounts like 1.250,50 or 1250.50 or -45,00 or 1.250,00-."""
    cleaned = amt_str.replace("TL", "").replace("TRY", "").replace("₺", "").replace("USD", "").replace("EUR", "").strip()
    cleaned = re.sub(r"[\s\xa0]+", "", cleaned)

    is_negative = False
    if cleaned.startswith("-") or cleaned.endswith("-"):
        is_negative = True
        cleaned = cleaned.replace("-", "")
    if cleaned.startswith("+") or cleaned.endswith("+"):
        cleaned = cleaned.replace("+", "")

    if "," in cleaned and "." in cleaned:
        # Check which comes last: in Turkish 1.250,50 comma is last; in 1,250.50 dot is last
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned and "." not in cleaned:
        cleaned = cleaned.replace(",", ".")
    elif "." in cleaned and "," not in cleaned:
        # If there are multiple dots or 3 digits after dot (e.g. 1.250), it's a thousand separator
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


def parse_turkish_date(date_str: str) -> Optional[date]:
    """Parse DD.MM.YYYY, DD/MM/YYYY, DD-MM-YYYY, DD.MM.YY, or '12 Ekim 2026'."""
    if not date_str:
        return None
    s = date_str.strip()
    # Check textual month format: e.g. "12 Ekim 2026" or "05 Eki 26"
    m_txt = re.match(r"^(\d{1,2})\s+([A-Za-zÇĞİÖŞÜçğıöşü]+)\s+(\d{2,4})$", s)
    if m_txt:
        try:
            d = int(m_txt.group(1))
            m_name = normalize_text_for_matching(m_txt.group(2))
            m = TR_MONTH_MAP.get(m_name) or TR_MONTH_MAP.get(m_name[:3])
            y = int(m_txt.group(3))
            if y < 100:
                y += 2000
            if m and 2000 <= y <= 2100:
                return date(y, m, d)
        except (ValueError, TypeError):
            return None

    cleaned = s.replace("/", ".").replace("-", ".")
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
    if "qnb finansbank" in t_norm or "qnb" in t_norm or "cardfinans" in t_norm:
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


def extract_installment_info(description: str) -> Optional[str]:
    """Detect installment tokens like 1/6, (02/12), 3. TAKSIT."""
    # Match (1/6) or 02/06 but avoid matching dates like 12/10/2026
    match = re.search(r"(?<![./\d])\(?\b(\d{1,2}\s*/\s*\d{1,2})\b\)?(?![./\d])", description)
    if match:
        token = match.group(1).replace(" ", "")
        parts = token.split("/")
        cur, tot = int(parts[0]), int(parts[1])
        if 1 <= cur <= tot <= 36 and tot > 1:
            return token
    match_txt = re.search(r"\b(\d{1,2})\.\s*taksit\b", description, re.IGNORECASE)
    if match_txt:
        return f"{match_txt.group(1)}/Taksit"
    return None


SKIP_SUMMARY_KEYWORDS = (
    "hesap kesim", "son odeme tarihi", "donem borcu", "onceki donem borcu",
    "asgari odeme", "toplam borc", "kullanilabilir limit", "kart limiti",
    "nakit avans limiti", "devir bakiye", "gecen donem", "hesap ozeti toplam",
    "toplam puan", "kazanilan puan", "kalan taksit", "gelecek donem",
    "donem ici hareketler toplam", "yillik akdi faiz", "gecikme faiz",
)

DATE_TOKEN_PATTERN = r"(?:\d{1,2}[./-]\d{1,2}[./-]\d{2,4}|\d{1,2}\s+[A-Za-zÇĞİÖŞÜçğıöşü]{3,10}\s+\d{2,4})"
AMOUNT_TOKEN_PATTERN = r"[+-]?(?:\d{1,3}(?:\.\d{3})+,\d{2}|\d+,\d{2}|\d{1,3}(?:,\d{3})+\.\d{2}|\d+\.\d{2})[+-]?"


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
            if abs(b_y - y_mid) <= 4.2:
                items.append((x0, text))
                placed = True
                break
        if not placed:
            buckets.append((y_mid, [(x0, text)]))

    buckets.sort(key=lambda b: b[0])
    raw_rows: list[tuple[float, str]] = []
    for b_y, items in buckets:
        items.sort(key=lambda it: it[0])
        line_str = " ".join(it[1] for it in items).strip()
        if line_str:
            raw_rows.append((b_y, line_str))

    # Merge wrapped continuation rows (within 16pt vertically) that don't start with a date
    # into the preceding date-starting row if the preceding row doesn't have an amount yet
    # or if the continuation row contains the amount for that multi-line cell
    merged_rows: list[str] = []
    last_date_y: Optional[float] = None
    date_start_re = re.compile(rf"^(?:[*•\-]|\d{{4}}\*+\d{{4}})?\s*({DATE_TOKEN_PATTERN})")
    amt_search_re = re.compile(AMOUNT_TOKEN_PATTERN)

    for b_y, line_str in raw_rows:
        starts_with_date = bool(date_start_re.match(line_str))
        if starts_with_date:
            merged_rows.append(line_str)
            last_date_y = b_y
        elif merged_rows and last_date_y is not None and (b_y - last_date_y) <= 18.0:
            # Check if this continuation line belongs to the active transaction row
            prev_line = merged_rows[-1]
            prev_has_amt = bool(amt_search_re.search(re.sub(rf"^{DATE_TOKEN_PATTERN}", "", prev_line)))
            curr_has_amt = bool(amt_search_re.search(line_str))
            if not prev_has_amt or curr_has_amt:
                merged_rows[-1] = f"{prev_line} {line_str}"
                last_date_y = b_y
            else:
                merged_rows.append(line_str)
        else:
            merged_rows.append(line_str)

    return merged_rows


def _parse_single_candidate_line(line: str) -> Optional[dict]:
    """Attempt to extract a transaction from a single horizontal row string."""
    # Strip optional leading bullet or masked card number
    cleaned_line = re.sub(r"^(?:[*•\-]+|\d{4}[\s*xX]+\d{4})\s+", "", line.strip())

    # Match leading date (and optional 2nd date like Kayıt/Valör tarihi)
    date_match = re.match(
        rf"^({DATE_TOKEN_PATTERN})(?:\s+{DATE_TOKEN_PATTERN})?\s+(.+)$",
        cleaned_line,
        re.IGNORECASE,
    )
    if not date_match:
        return None

    date_raw, rest = date_match.group(1), date_match.group(2).strip()
    tx_date = parse_turkish_date(date_raw)
    if not tx_date:
        return None

    # Find all currency amount tokens in the rest of the line
    # Avoid matching installment fractions like 1/6 or dates
    amt_iter = list(
        re.finditer(
            rf"(?<![/\d])({AMOUNT_TOKEN_PATTERN})\s*(TL|TRY|₺|USD|EUR)?\s*([+-]|(?:\(?[BAba]\)?)|Borç|Alacak)?(?=\s|$)",
            rest,
            re.IGNORECASE,
        )
    )
    if not amt_iter:
        return None

    # Pick the primary transaction amount:
    # Usually if there are 2 amounts at the end:
    # - If the last one is followed by Puan/Bonus/Mil or is tiny (< 5% of previous), pick the previous one.
    # - If it's an installment row with Total Amount + Monthly Installment (e.g. 12.000,00 2.000,00), pick the first transaction amount or the TL amount.
    chosen_match = amt_iter[-1]
    if len(amt_iter) >= 2:
        last_m = amt_iter[-1]
        prev_m = amt_iter[-2]
        after_last = rest[last_m.end():].strip().lower()
        between = rest[prev_m.end():last_m.start()].strip().lower()
        try:
            v_last = abs(parse_turkish_amount(last_m.group(1)))
            v_prev = abs(parse_turkish_amount(prev_m.group(1)))
            # If the last column is a small bonus/point column (or 0,00) while prev_m has TL or is much larger
            if v_last == 0 and v_prev > 0:
                chosen_match = prev_m
            elif any(p in after_last or p in between for p in ("puan", "bonus", "mil", "chip", "worldpuan", "maximiles")):
                chosen_match = prev_m
            elif prev_m.group(2) and not last_m.group(2) and v_last < v_prev * 0.15:
                chosen_match = prev_m
        except ValueError:
            pass

    desc_raw = rest[:chosen_match.start()].strip()
    # If chosen_match wasn't the first amount in the tail, strip trailing amounts from desc_raw
    if len(amt_iter) >= 2 and chosen_match == amt_iter[-1]:
        # Keep description clean if the second-to-last was right before it and part of columns
        pass

    desc_clean = re.sub(r"\s+", " ", desc_raw).strip(" -·|")
    if len(desc_clean) < 2:
        return None

    norm_desc = normalize_text_for_matching(desc_clean)
    if any(skip_kw in norm_desc for skip_kw in SKIP_SUMMARY_KEYWORDS):
        return None

    amt_raw = chosen_match.group(1)
    sign_raw = chosen_match.group(3) or ""
    # Check if there is a leading sign right before the amount in `rest`
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
    is_repayment = is_card_repayment_or_refund(desc_clean)
    category, conf = guess_category(desc_clean)

    # Note: only treat as income if it's an explicit repayment/refund OR has an explicit Alacak/+ sign
    # (or negative amount when not an expense processor)
    is_expense_processor = any(proc in norm_desc for proc in EXPENSE_PAYMENT_PROCESSORS)
    if is_repayment or (is_alacak_sign and not is_expense_processor) or (amt < 0 and not is_expense_processor):
        tx_type = "income"
        final_amt = abs(amt)
    else:
        tx_type = "expense"
        final_amt = abs(amt)

    inst_info = extract_installment_info(desc_clean)

    return {
        "occurred_on": tx_date.isoformat(),
        "raw_date": date_raw,
        "description": desc_clean,
        "amount": round(final_amt, 2),
        "type": tx_type,
        "suggested_category": category if tx_type == "expense" else "Gelir",
        "confidence": conf,
        "installment_info": inst_info,
    }


def _extract_multiline_blocks(lines: list[str]) -> list[dict]:
    """Scan vertical line sequences where Date, multi-line Description, and Amount are on separate lines."""
    date_only_re = re.compile(rf"^(?:[*•\-]+|\d{{4}}[\s*xX]+\d{{4}})?\s*({DATE_TOKEN_PATTERN})$", re.IGNORECASE)
    amt_only_re = re.compile(
        rf"^({AMOUNT_TOKEN_PATTERN})\s*(TL|TRY|₺|USD|EUR)?\s*([+-]|(?:\(?[BAba]\)?)|Borç|Alacak)?$",
        re.IGNORECASE,
    )

    results: list[dict] = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i].strip()
        # First try single-line parse
        single = _parse_single_candidate_line(line)
        if single:
            results.append(single)
            i += 1
            continue

        # Check if this line is a standalone date
        dm = date_only_re.match(line)
        if dm:
            date_raw = dm.group(1)
            tx_date = parse_turkish_date(date_raw)
            if tx_date:
                # Look ahead up to 6 lines for description lines + amount line
                desc_parts: list[str] = []
                j = i + 1
                matched_block = False
                while j < min(n, i + 7):
                    cand = lines[j].strip()
                    # Skip a second date (valor/kayıt tarihi) right after the first date
                    if j == i + 1 and date_only_re.match(cand):
                        j += 1
                        continue
                    # If we hit another date after collecting description without amount, stop
                    if date_only_re.match(cand) or _parse_single_candidate_line(cand):
                        break
                    am = amt_only_re.match(cand)
                    if am and desc_parts:
                        combined_line = f"{date_raw} {' '.join(desc_parts)} {cand}"
                        parsed = _parse_single_candidate_line(combined_line)
                        if parsed:
                            results.append(parsed)
                            i = j + 1
                            matched_block = True
                            break
                    else:
                        desc_parts.append(cand)
                    j += 1
                if matched_block:
                    continue
        i += 1

    return results


def parse_pdf_statement(file_bytes: bytes) -> dict:
    """Extract and parse credit card transactions from PDF statement bytes."""
    doc = pymupdf.open(stream=file_bytes, filetype="pdf")
    all_text = ""
    raw_lines: list[str] = []
    coord_lines: list[str] = []

    for page in doc:
        page_text = page.get_text("text")
        all_text += page_text + "\n"
        for line in page_text.splitlines():
            stripped = line.strip()
            if stripped:
                raw_lines.append(stripped)
        coord_lines.extend(_reconstruct_horizontal_rows(page))

    bank_name = detect_bank(all_text)

    raw_txs = _extract_multiline_blocks(raw_lines)
    coord_txs = _extract_multiline_blocks(coord_lines)

    # Choose the extraction strategy that recovered more total transaction volume/count,
    # and also merge any unique transactions found only in the other strategy!
    primary = coord_txs if len(coord_txs) >= len(raw_txs) else raw_txs
    secondary = raw_txs if primary is coord_txs else coord_txs

    # Merge unique items from secondary that weren't captured in primary (by date + amount)
    seen_counts: dict[tuple[str, float, str], int] = {}
    merged: list[dict] = []
    for tx in primary:
        key = (tx["occurred_on"], round(tx["amount"], 2), tx["type"])
        seen_counts[key] = seen_counts.get(key, 0) + 1
        merged.append(tx)

    sec_counts: dict[tuple[str, float, str], int] = {}
    for tx in secondary:
        key = (tx["occurred_on"], round(tx["amount"], 2), tx["type"])
        sec_counts[key] = sec_counts.get(key, 0) + 1
        if sec_counts[key] > seen_counts.get(key, 0):
            merged.append(tx)
            seen_counts[key] = sec_counts[key]

    return {
        "bank_name": bank_name,
        "total_found": len(merged),
        "transactions": merged,
    }
