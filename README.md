# Budget Control

Kişisel bütçe, gider ve abonelik takibi için FastAPI tabanlı bir API + basit bir web arayüzü.

## Özellikler

- E-posta/şifre ile kayıt ve giriş (JWT access + refresh token)
- Gelir/gider işlemleri: tutar, kategori, not, tarih
- Abonelik takibi: tutar, ödeme periyodu (haftalık/aylık/yıllık), sonraki ödeme tarihi
- Genel bakış: bu ayki gelir/gider/net bakiye, aylık abonelik maliyeti, yaklaşan ödemeler

## Kurulum

```bash
python -m venv venv
source venv/Scripts/activate  # Windows (Git Bash)
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload
```

Uygulama arayüzü: `http://127.0.0.1:8000/app/`

## Test

```bash
pytest -q
```
