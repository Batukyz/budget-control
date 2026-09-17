# Budget Control

Kişisel bütçe, gider ve abonelik takibi için FastAPI tabanlı bir API + basit bir web arayüzü.

## Özellikler

- E-posta/şifre ile kayıt ve giriş (JWT access + refresh token)
- Gelir/gider işlemleri: tutar, kategori, not, tarih
- Abonelik takibi: tutar, ödeme periyodu (haftalık/aylık/yıllık), sonraki ödeme tarihi
- Genel bakış: bu ayki gelir/gider/net bakiye, aylık abonelik maliyeti, yaklaşan ödemeler

## Kurulum

PowerShell:

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload
```

Git Bash:

```bash
source venv/Scripts/activate
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload
```

VarsayÄ±lan veritabanÄ± proje kÃ¶kÃ¼ndeki SQLite `budget.db` dosyasÄ±dÄ±r. FarklÄ± bir
SQLAlchemy baÄŸlantÄ±sÄ± iÃ§in `DATABASE_URL` kullanÄ±labilir. CanlÄ± ortamda `APP_ENV=production`
ve rastgele, gizli bir `SECRET_KEY` tanÄ±mlamak zorunludur.

Uygulama arayüzü: `http://127.0.0.1:8000/app/`

## Test

```bash
pytest -q
```
