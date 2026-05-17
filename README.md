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

## Tek komutla tam stack (önerilen)

Panel + Postgres + Redis + Postfix + Dovecot **aynı `docker-compose.yml` içinde** — host’ta ayrı `docker build` / `jir_*` kurulumu gerekmez.

```bash
cp .env.compose.example .env
# .env içinde POSTGRES_PASSWORD ve JIR_LOCAL_KEY düzenleyin
docker compose up -d --build
```

**Dokploy / Coolify:** kaynak türü **Docker Compose** → `docker-compose.yml`. Ortam: `.env.dokploy.example` veya `.env.coolify`. `JIR_COMPOSE_STACK=1` zorunlu.

Sunucuda `git clone` + `docker compose up` **yapmayın** — PaaS deploy etsin. Kurulum sihirbazı compose modunda Docker API kullanmaz.

### Dokploy (özet)

1. Proje → **Compose** → GitHub `mrcengiz-owner/jirmail`, branch `main`
2. **Environment** → `.env.dokploy.example` içeriği (şifreleri değiştirin)
3. **Domains** → `django` servisi, port **8000**
4. Deploy; ilk açılışta `/setup/` sihirbazı
5. DNS: `A` mail → sunucu IP; SMTP 25/587, IMAP 993 firewall’da açık

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
- Saf CSS (`static/css/main.css` + `brand.css`) — ek bileşenler için doğrudan CSS veya yeni bir stylesheet ekleyin

**Altyapı**
- Docker Compose (django, celery, celery-beat, postgres, redis, postfix, dovecot, docker-proxy)
- Coolify deploy desteği

## Hızlı Başlangıç

### Geliştirme (lokal)

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

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
static/       main.css (tek stylesheet kaynağı), brand.css, app.js
dovecot/      Dovecot imajı; `*.tpl` şablonlar + ortam (`DB_*`, `MAIL_DOMAIN`) — sırlar repoda yok
```

### Dovecot’u sunucuda elle derlemek (Coolify)

`/app` yalnızca **panel konteynerinin içinde** vardır; host’ta `docker build /app/dovecot` çalışmaz. Örnek:

```bash
export PANEL=y6171w3adxrsvye799k5htub-010053730009   # büyük harf PANEL
chmod +x scripts/rebuild-dovecot-on-host.sh
./scripts/rebuild-dovecot-on-host.sh
```

`panel=` küçük harf ile `$PANEL` boş kalır; `docker cp` hata verir.

Kurulum sihirbazı (`setup.html` → bootstrap) güncel kodu deploy ettikten sonra imajı panel üzerinden otomatik derler; tercih edilen yol budur.
```

## Stil (saf CSS)

Arayüz stilleri `static/css/main.css` içindedir (önceki Tailwind çıktısı tek dosyada konsolide edilmiştir). Yeni görünüm veya bileşen eklerken:

1. `main.css` sonuna kurallar ekleyebilir veya `static/css/` altında yeni bir `.css` oluşturup `templates/base.html` içinde `{% static %}` ile bağlayabilirsiniz.
2. Şablonda **yeni** “utility” benzeri sınıf adları kullanırsanız, bunların karşılığı `main.css` içinde tanımlı olmalıdır; otomatik derleme adımı yoktur.

## Lisans

Bu proje özel/şirket içi kullanım içindir.
