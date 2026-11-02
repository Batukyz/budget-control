# Budget Control

**[Türkçe](#-türkçe) | [English](#-english)**

---

## 🇹🇷 Türkçe

Kişisel bütçe, gelir-gider dengesi, kredi kartları, taksitler, abonelikler ve banka ekstresi aktarımlarını tek bir yerden yönetmenizi sağlayan modern ve duyarlı (responsive) web uygulaması.

### ✨ Özellikler

- **Özet Paneli (Dashboard):** Gelir-gider dengesi, kategori bazlı analizler ve finansal durum özeti
- **Gelir / Gider Takibi:** Detaylı işlem kayıtları, filtreleme ve kategori yönetimi
- **Bütçe Yönetimi:** Kategori bazlı aylık bütçe limitleri ve harcama takibi
- **Kredi Kartları & Taksit Sistemi:** Kredi kartı limit/borç takibi, taksitli harcamalar, ödeme ve vade takibi
- **PDF Ekstre Aktarımı (Statement Import):** Kredi kartı ve banka PDF ekstrelerinden akıllı işlem ayrıştırma, etkileşimli önizleme/düzenleme ve mükerrer kayıt koruması
- **Abonelikler & Tekrarlayan İşlemler:** Düzenli ödemelerin ve aboneliklerin otomatik takibi
- **Veri Taşınabilirliği:** CSV içe/dışa aktarma (import/export) ve tam JSON yedekleme/geri yükleme (backup/restore)
- **Güvenlik & Hesap Yönetimi:** JWT tabanlı kimlik doğrulama (HttpOnly çerez desteği), istek sınırlandırma (rate limiting) ve hesap sıfırlama
- **Modern Arayüz:** Karanlık / Aydınlık mod (Dark / Light mode), mobil uyumlu (responsive) tasarım ve dokunmatik yenileme (pull-to-refresh) desteği

### 🛠 Teknoloji Yığını

- **Backend:** Python, FastAPI, SQLAlchemy, Alembic, Pydantic
- **Kimlik Doğrulama & Güvenlik:** PyJWT, SlowAPI (Rate Limiting)
- **Frontend:** Vanilla JavaScript, HTML5, CSS3 (`/app` altında statik olarak sunulur)
- **Test:** Pytest, HTTPX

### 🚀 Kurulum ve Çalıştırma

**Windows (PowerShell):**

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload
```

**macOS / Linux:**

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload
```

- **Uygulama Arayüzü:** `http://127.0.0.1:8000/` (otomatik olarak `/app/` adresine yönlendirir)
- **API Dokümantasyonu (Swagger UI):** `http://127.0.0.1:8000/docs`

### 🧪 Testler

Testleri çalıştırmak için:

```bash
pytest
```

---

## 🇬🇧 English

A modern, responsive web application designed to manage your personal budget, income-expense balance, credit cards, installments, subscriptions, and bank statement imports all in one place.

### ✨ Features

- **Dashboard:** Income-expense balance, category breakdowns, and financial overview
- **Income / Expense Tracking:** Detailed transaction logging, filtering, and category management
- **Budgets:** Category-based monthly budget limits and spending progress tracking
- **Credit Cards & Installment System:** Credit card limit/balance tracking, installment purchases, payment and due date tracking
- **PDF Statement Import:** Smart transaction extraction from PDF bank/credit card statements with interactive preview/review and duplicate protection
- **Subscriptions & Recurring Transactions:** Automated tracking for recurring bills and subscriptions
- **Data Portability:** CSV import/export and full JSON backup/restore
- **Security & Account Management:** JWT-based authentication (with HttpOnly cookie support), rate limiting, and full account reset
- **Modern UI/UX:** Dark / Light mode, mobile-responsive layout, and mobile pull-to-refresh gesture support

### 🛠 Tech Stack

- **Backend:** Python, FastAPI, SQLAlchemy, Alembic, Pydantic
- **Authentication & Security:** PyJWT, SlowAPI (Rate Limiting)
- **Frontend:** Vanilla JavaScript, HTML5, CSS3 (served statically under `/app`)
- **Testing:** Pytest, HTTPX

### 🚀 Installation & Usage

**Windows (PowerShell):**

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload
```

**macOS / Linux:**

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload
```

- **Application UI:** `http://127.0.0.1:8000/` (automatically redirects to `/app/`)
- **API Documentation (Swagger UI):** `http://127.0.0.1:8000/docs`

### 🧪 Running Tests

To run the test suite:

```bash
pytest
```
