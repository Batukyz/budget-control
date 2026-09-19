# Budget Control

Kişisel bütçe, gider ve abonelik takibi için FastAPI tabanlı bir API + basit bir web arayüzü.

## Özellikler

- E-posta/şifre ile kayıt ve giriş (JWT access + refresh token)
- Gelir/gider işlemleri: tutar, kategori, not, tarih
- Abonelik takibi: tutar, ödeme periyodu (haftalık/aylık/yıllık), sonraki ödeme tarihi
- Kredi kartı taksit yönetimi: taksit planı, deterministik kuruş yuvarlama, ay sonu takvim hesaplaması, ödeme takibi ve borç entegrasyonu
- Hesap sıfırlama: kullanıcı kimliğini koruyarak finansal verileri güvenli ve atomik sıfırlama
- Genel bakış: bu ayki gelir/gider/net bakiye, aylık abonelik maliyeti, yaklaşan ödemeler, taksitler

## Taksitli Harcamalar ve Hesap Sıfırlama (M6)

- **Kredi Kartı Taksit Sistemi**:
  - Kredi kartına bağlı taksit planları (`InstallmentPlan`) ve takvim vadeleri (`InstallmentPayment`).
  - **Deterministik Yuvarlama Kuralı**: Kuruş kaybını önlemek için son taksit tutarı `toplam_tutar - sum(önceki_taksitler)` formülüyle hesaplanır (örn. 10.000 TL / 3 taksit -> 3.333,33, 3.333,33, 3.333,34 TL).
  - **Takvim İlerlemesi**: Ay sonu başlangıçlı taksitler (örn. 31 Ocak) takip eden ayların son geçerli gününe (örn. 28/29 Şubat, 31 Mart, 30 Nisan) otomatik ayarlanır; artık yıl kontrolü içerir.
  - **Ödeme Döngüsü & Kart Borcu**: Taksit ödendiğinde anında Activity gider kaydına ve kartın güncel borcuna yansıtılır. İşlem idempotenttir.
  - **Aktif Taksit Koruması**: Devam eden aktif taksiti bulunan kredi kartlarının silinmesi engellenir.
- **Hesabı Sıfırla**:
  - `Ayarlar → Veri` altında `SIFIRLA` metni yazılarak explicit tehlike onayıyla çalışır.
  - Kullanıcı hesabı silinmeden, yalnızca kullanıcıya ait finansal kayıtlar atomik olarak temizlenir.
- **JSON Yedekleme & Geri Yükleme**:
  - Taksit planları ve ödemeleri tam olarak dışa ve içe aktarılabilir. Eski yedeklerle geriye dönük tam uyumludur.

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
