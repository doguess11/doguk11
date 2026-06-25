# BT Yönetim Paneli

Bu proje, yerel ağınızda Cisco switch'leri Telnet ile yönetmek ve kullanıcı hızlarını canlı takip etmek için FastAPI tabanlı bir backend ve Bootstrap tabanlı basit bir frontend sağlar.

Kurulum

1. Sanal ortam oluşturun ve etkinleştirin.
2. Gereksinimleri yükleyin:

```bash
pip install -r requirements.txt
```

Çalıştırma

```bash
python main.py
```

Arayüzü açmak için tarayıcıda `http://localhost:8000/` adresine gidin.

Notlar
- Switchlere sadece Telnet ile bağlanılır (SSH yok).
- Excel dosyaları `kullanicilar.xlsx` ve `switchler.xlsx` proje dizininde oluşturulur.
- Yapılan hız değişiklikleri `islem_loglari.txt` dosyasına loglanır.
