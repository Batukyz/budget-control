# Budget Control

Kişisel bütçe, gelir-gider dengesi, kredi kartları, taksitler ve abonelikleri tek bir yerden yönetmenizi sağlayan modern ve responsive web uygulaması.

## Özellikler

- Dashboard
- Gelir / gider takibi
- Bütçeler
- Abonelikler
- Tekrarlayan işlemler
- Kredi kartları
- Kredi kartı taksit sistemi
- Taksit ödeme ve vade takibi
- CSV import / export
- JSON backup / restore
- Hesap sıfırlama
- Dark / Light mode
- Responsive tasarım

## Kurulum

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload
```

Uygulama arayüzü: `http://127.0.0.1:8000/`
