# Jîr-Mail

> Kendi sunucunda barındırılan (self-hosted), Docker tabanlı kurumsal mail platformu ve yönetim paneli.

Jîr-Mail, **Postfix + Dovecot + PostgreSQL** mail yığınını tek tıkla kurup web arayüzünden yönetmeni sağlayan bir komut merkezidir. Domain, hesap, kota, DKIM/SPF/DMARC, container, yedek ve uyarı yönetimini tek bir panelden yapabilirsin.

## Özellikler

- **Setup Wizard** — İlk açılışta domain, admin hesabı ve veritabanı (SQLite veya PostgreSQL) seçimini adım adım yapar
- **Multi-Tenant SaaS Yapısı** — `SystemConfig` tabanlı tier sistemi (Free / Pro / Enterprise) ile hesap limitleri
- **Domain Yönetimi** — Otomatik DKIM (RSA 2048-bit) anahtar üretimi, SPF/DMARC kayıt önerileri, periyodik DNS doğrulama
- **Hesap Yönetimi** — Bcrypt parola, rol bazlı yetkiler (FULL / SEND / RECV / BLOCK), kota, imza, auto-responder, mail forwarding
- **Container Kontrolü** — Docker socket-proxy üzerinden güvenli (read-only API) container start/stop/restart
- **Yedekleme** — DB dump + email vhosts + config dosyaları tek bir `tar.gz` arşivinde; Celery Beat ile zamanlanmış yedek
- **Sistem Uyarıları** — CPU/RAM/disk/mail kuyruğu/quota threshold'ları, periyodik kontrol, otomatik alert üretimi
- **Webmail UI** — 3 sütunlu Gmail tarzı kullanıcı paneli (IMAP entegrasyonu planlanan aşamada)

## Coolify / PaaS üretim kontrolü

Adım adım kontrol listesi: [docs/coolify-kontrol-listesi.md](docs/coolify-kontrol-listesi.md).

**Deploy kontrolü (otomatik):**

- Her container start’ta: `python manage.py check_deploy` (`docker-entrypoint.sh`)
- Panel: **Ayarlar → Deploy uyumluluk** veya `GET /api/management/deploy-readiness` (FULL oturum)
- Kurulum sihirbazı adım 1: `GET /api/installer/bootstrap` → `deploy_readiness`

```bash
python manage.py check_deploy          # insan okunur özet
python manage.py check_deploy --json   # CI / Coolify post-deploy script
python manage.py check_deploy --fail-on-error
```

**Önemli:** Lokal **Docker tam kurulum** (`docker_stack`) Coolify tek uygulama konteynerinde çalışmaz. Sunucuda **Ortam veritabanı (DATABASE_URL)** + ayrı Postfix/Dovecot servisleri kullanın; `JIR_CONTAINER_POSTFIX` / `JIR_CONTAINER_DOVECOT` env ile gerçek konteyner adlarını verin.

## Teknoloji Yığını

**Backend**
- Django 5.2 + django-ninja (REST API)
- PostgreSQL 17 (veya SQLite fallback)
- Celery 5.4 + Redis 7 (zamanlı görevler, DNS auto-check, alert evaluation)
- Gunicorn (production WSGI)
- bcrypt, cryptography, psutil, docker SDK, dnspython

**Mail**
- Postfix (`boky/postfix`) — SMTP (25, 587)
- Dovecot — IMAP/POP3 (993, 143), PostgreSQL passdb/userdb

**Frontend**
- Django Templates (SSR)
- Alpine.js 3.x (reaktif UI)
- Tailwind CSS 3.4 (local build, JIT)

**Altyapı**
- Docker Compose (django, celery, celery-beat, postgres, redis, postfix, dovecot, docker-proxy)
- Coolify deploy desteği

## Hızlı Başlangıç

### Geliştirme (lokal)

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

npm install
npm run build

python manage.py migrate
python manage.py runserver
```

Tarayıcıdan `http://localhost:8000/` adresine git → Setup Wizard seni karşılar.

### Production (Docker)

```bash
cp .env.coolify .env
# .env içindeki POSTGRES_PASSWORD, JIR_LOCAL_KEY, MAIL_DOMAIN değerlerini doldur

docker compose up -d
```

İlk açılışta `http://<sunucu>:8000/setup/` Setup Wizard'ı görünür.

## Dizin Yapısı

```
config/         Django settings, URL, Celery konfigürasyonu
docs/           Coolify / PaaS üretim kontrol listesi
core/           MailDomain, MailAccount, Backup modelleri + API
management/    Admin operasyonları, sistem sağlık, container API
saas/           SystemConfig, Alert, AlertThreshold modelleri
backup/         Yedekleme/restore API
alerts/         Threshold tabanlı uyarı sistemi + Celery taskları
jir_core/      Kurulum durumu middleware
templates/    Django HTML şablonları (pages/, partials/)
static/         Tailwind input.css, build edilmiş main.css, app.js
dovecot/      Dovecot imajı; `*.tpl` şablonlar + ortam (`DB_*`, `MAIL_DOMAIN`) — sırlar repoda yok
```

## Tailwind CSS Build

```bash
npm run watch        # Geliştirme — değişiklikleri otomatik yeniden derle
npm run build        # Tek seferlik build
npm run build:prod   # Minified production build
```

## Lisans

Bu proje özel/şirket içi kullanım içindir.
