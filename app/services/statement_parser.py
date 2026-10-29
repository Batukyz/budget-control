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
        "kasap", "fırın", "firin", "unlu mamul", "bakkal", "market", "peynirci"
    ],
    "Yeme & İçme": [
        "yemeksepeti", "getir", "trendyol yemek", "burger king", "mcdonalds", "starbucks",
        "kahve", "cafe", "restaurant", "restorant", "lokanta", "pide", "kebap", "döner",
        "doner", "börek", "borek", "pizza", "sushi", "tatlı", "tatli", "köfte", "kofte",
        "pastane", "meyhane", "bar", "pub", "meyve suyu", "lahmacun", "dürüm", "durum"
    ],
    "Ulaşım & Akaryakıt": [
        "shell", "opet", "bp", "petrol ofisi", "total", "aygaz", "tp petrol", "biletix",
        "obilet", "pegasus", "flypgs", "thy", "turkish air", "ajet", "anadolujet", "tcdd",
        "marmaray", "istanbulkart", "izmirimkart", "ankarakart", "otobüs", "otobus", "metro",
        "taksi", "uber", "bitaksi", "otopark", "ispark", "hgs", "ogs", "karayollari",
        "yolcu360", "rent a car", "akaryakit", "benzin"
    ],
    "Abonelikler": [
        "netflix", "spotify", "youtube", "icloud", "apple.com/bill", "itunes", "google play",
        "google storage", "amazon prime", "prime video", "disney", "blutv", "exxen", "gain",
        "chatgpt", "openai", "midjourney", "anthropic", "github", "steam", "playstation",
        "psn", "xbox", "game pass", "deezer", "storytel"
    ],
    "Faturalar": [
        "turkcell", "vodafone", "turk telekom", "turktelekom", "enerjisa", "başkent elektrik",
        "baskent elektrik", "ck bogazici", "gediz elektrik", "toroslar", "igdas", "aski",
        "iski", "izsu", "dogalgaz", "doğalgaz", "elektrik", "su faturasi", "turknet",
        "superonline", "millenicom", "d-smart", "digiturk", "tivibu", "fatura"
    ],
    "Alışveriş & Giyim": [
        "trendyol", "hepsiburada", "hepsi burada", "amazon.com", "amazon com", "zara",
        "bershka", "pull&bear", "pull and bear", "stradivarius", "massimo dutti", "mango",
        "h&m", "koton", "lc waikiki", "lcw", "mavi", "defacto", "boyner", "beymen",
        "decathlon", "nike", "adidas", "puma", "under armour", "flo", "skechers",
        "derimod", "vakko", "ipekyol", "network"
    ],
    "Teknoloji & Elektronik": [
        "vatan bilgisayar", "mediamarkt", "media markt", "teknosa", "itopya", "tebilon",
        "sinerji", "d&r", "dr.com", "monster notebook", "gaming", "bilgisayar", "elektronik",
        "apple store", "gürgençler", "gurgencler", "troy"
    ],
    "Sağlık & Kozmetik": [
        "eczane", "optik", "hastane", "tıp merkezi", "tip merkezi", "gratis", "watsons",
        "sephora", "rossmann", "kozmetik", "diş", "dental", "klinik", "laboratuvar",
        "veteriner", "medikal"
    ],
    "Eğitim": [
        "udemy", "coursera", "edx", "kitap", "kitapyurdu", "bkm kitap", "idefix",
        "üniversite", "universite", "kırtasiye", "kirtasiye", "okul", "kolej", "kurs", "akademi"
    ],
    "Eğlence & Sosyal": [
        "cinemapink", "paribu cineverse", "sinema", "tiyatro", "konser", "biletinial",
        "passo", "etkinlik", "müze", "muze", "lunapark", "bowling", "oyun"
    ],
    "Ödeme / Gelir": [
        "ödeme", "odeme", "yatırılan", "yatirilan", "eft", "havale", "maaş", "maas",
        "alacak", "iade", "borç kapama", "kart ödeme", "nakit yatirma", "avans"
    ]
}

# Pre-compile normalized category keywords
NORMALIZED_CATEGORY_KEYWORDS = {
    cat: [normalize_text_for_matching(kw) for kw in keywords]
    for cat, keywords in CATEGORY_KEYWORDS.items()
}


def guess_category(description: str) -> tuple[str, float]:
    """Inspect description and suggest a high-confidence category based on Turkish keywords."""
    norm_desc = normalize_text_for_matching(description)
    
    # Check income/payment first
    for kw in NORMALIZED_CATEGORY_KEYWORDS["Ödeme / Gelir"]:
        if kw in norm_desc:
            return "Ödeme / Gelir", 0.95

    # Check other categories
    for cat, keywords in NORMALIZED_CATEGORY_KEYWORDS.items():
        if cat == "Ödeme / Gelir":
            continue
        for kw in keywords:
            if kw in norm_desc:
                return cat, 0.85

    return "Diğer", 0.30


def parse_turkish_amount(amt_str: str) -> float:
    """Parse amounts like 1.250,50 or 1250.50 or -45,00."""
    cleaned = amt_str.replace("TL", "").replace("TRY", "").replace("₺", "").strip()
    cleaned = re.sub(r"[\s\xa0]+", "", cleaned)
    
    # Handle negative signs or trailing minus (e.g. 150,00 -)
    is_negative = False
    if cleaned.startswith("-") or cleaned.endswith("-"):
        is_negative = True
        cleaned = cleaned.replace("-", "")

    # Turkish format standard: 1.250,50 -> 1250.50
    if "," in cleaned and "." in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    elif "," in cleaned and "." not in cleaned:
        cleaned = cleaned.replace(",", ".")

    val = float(cleaned)
    return -val if is_negative else val


def parse_turkish_date(date_str: str) -> Optional[date]:
    """Parse DD.MM.YYYY, DD/MM/YYYY, DD-MM-YYYY, DD.MM.YY."""
    cleaned = date_str.strip().replace("/", ".").replace("-", ".")
    parts = cleaned.split(".")
    if len(parts) != 3:
        return None
    try:
        d, m, y = int(parts[0]), int(parts[1]), int(parts[2])
        if y < 100:
            y += 2000
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
    if "teb" in t_norm or "turk ekonomi bankasi" in t_norm:
        return "TEB"
    if "denizbank" in t_norm:
        return "DenizBank"
    return "Banka Ekstresi (Genel)"


def extract_installment_info(description: str) -> Optional[str]:
    """Detect installment tokens like 1/6, (02/12), 3. TAKSIT."""
    match = re.search(r"\(?\b(\d{1,2}\s*/\s*\d{1,2})\b\)?", description)
    if match:
        return match.group(1).replace(" ", "")
    match_txt = re.search(r"\b(\d{1,2})\.\s*taksit\b", description, re.IGNORECASE)
    if match_txt:
        return f"{match_txt.group(1)}/Taksit"
    return None


def parse_pdf_statement(file_bytes: bytes) -> dict:
    """Extract and parse credit card transactions from PDF statement bytes."""
    doc = pymupdf.open(stream=file_bytes, filetype="pdf")
    all_text = ""
    lines: list[str] = []

    for page in doc:
        page_text = page.get_text("text")
        all_text += page_text + "\n"
        for line in page_text.splitlines():
            stripped = line.strip()
            if stripped:
                lines.append(stripped)

    bank_name = detect_bank(all_text)

    # Regex patterns for statement rows
    # Pattern 1: Date at start of line: "14.10.2026 ... 150,00 TL" or "14/10/2026 MİGROS 450,00"
    row_regex = re.compile(
        r"^(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})\s+(.+?)\s+([+-]?\d{1,3}(?:\.\d{3})*,\d{2}|[+-]?\d+,\d{2}|[+-]?\d+\.\d{2})\s*(TL|TRY|₺)?\s*([+-]|(?:\(?[BAba]\)?))?$",
        re.IGNORECASE
    )

    transactions: list[dict] = []
    
    # Scan through extracted lines
    for i, line in enumerate(lines):
        m = row_regex.match(line)
        if m:
            date_raw, desc_raw, amt_raw, curr_raw, sign_raw = m.groups()
            tx_date = parse_turkish_date(date_raw)
            if not tx_date:
                continue

            try:
                amt = parse_turkish_amount(amt_raw)
            except ValueError:
                continue

            is_alacak = bool(sign_raw and any(s in sign_raw.upper() for s in ("A", "+")))
            desc_clean = re.sub(r"\s+", " ", desc_raw).strip()
            category, conf = guess_category(desc_clean)
            
            norm_desc = normalize_text_for_matching(desc_clean)
            is_payment_desc = category == "Ödeme / Gelir" or any(w in norm_desc for w in ("odeme", "iade", "alacak", "yatirilan"))
            
            if is_alacak or is_payment_desc or amt < 0:
                tx_type = "income"
                final_amt = abs(amt)
            else:
                tx_type = "expense"
                final_amt = abs(amt)

            if final_amt <= 0:
                continue

            inst_info = extract_installment_info(desc_clean)

            transactions.append({
                "occurred_on": tx_date.isoformat(),
                "raw_date": date_raw,
                "description": desc_clean,
                "amount": final_amt,
                "type": tx_type,
                "suggested_category": category if tx_type == "expense" else "Gelir",
                "confidence": conf,
                "installment_info": inst_info,
            })
            continue

        # Pattern 2: Multi-line layout where Date is on line i, Description is line i+1, Amount follows
        date_only_match = re.match(r"^(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})$", line)
        if date_only_match and i + 2 < len(lines):
            cand_date = parse_turkish_date(date_only_match.group(1))
            cand_desc = lines[i + 1]
            cand_amt_line = lines[i + 2]
            amt_match = re.search(r"([+-]?\d{1,3}(?:\.\d{3})*,\d{2}|[+-]?\d+,\d{2})\s*(?:TL|TRY|₺)?", cand_amt_line)
            if cand_date and amt_match and len(cand_desc) > 2 and not re.match(r"^\d{1,2}[./-]", cand_desc):
                try:
                    amt = parse_turkish_amount(amt_match.group(1))
                    if amt > 0:
                        desc_clean = cand_desc.strip()
                        cat, conf = guess_category(desc_clean)
                        norm_desc = normalize_text_for_matching(desc_clean)
                        is_payment = cat == "Ödeme / Gelir" or any(w in norm_desc for w in ("odeme", "iade", "alacak"))
                        transactions.append({
                            "occurred_on": cand_date.isoformat(),
                            "raw_date": date_only_match.group(1),
                            "description": desc_clean,
                            "amount": abs(amt),
                            "type": "income" if is_payment else "expense",
                            "suggested_category": cat if not is_payment else "Gelir",
                            "confidence": conf,
                            "installment_info": extract_installment_info(desc_clean),
                        })
                except ValueError:
                    pass

    return {
        "bank_name": bank_name,
        "total_found": len(transactions),
        "transactions": transactions,
    }
