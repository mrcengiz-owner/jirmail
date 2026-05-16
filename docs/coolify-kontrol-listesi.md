# Coolify’da Jîr-Mail — üretim kontrol listesi

Coolify’da bir proje deploy edildiğinde her servisin **kendi konteyneri** ve çoğu zaman **projeye özgü, uzun veya rastgele** bir adı olur. Panel ve API ise varsayılan olarak `jir_postfix`, `jir_dovecot` gibi **sabit isimler** bekleyebilir. Bu liste, Coolify ortamında her şeyi tek tek doğrulaman için.

---

## 0) Kavram haritası

| Bileşen | Coolify’da tipik durum |
|--------|-------------------------|
| Django (panel) | Bir “application” servisi; kendi konteyneri |
| PostgreSQL | Aynı projede managed DB veya harici servis; `DATABASE_URL` ile bağlanır |
| Postfix / Dovecot / Redis | Aynı compose içinde ek servisler veya **ayrı** Coolify uygulamaları |
| Docker API | Panelden konteyner start/stop için Django’nun **aynı Docker daemon**’a erişmesi gerekir (soket veya `DOCKER_HOST`) |

---

## 1) Gerçek konteyner adlarını bul (Coolify arayüzünde “Containers” diye bir sekme olmayabilir)

Coolify sürümüne göre menü adları değişir; bazı kurulumlarda konteyner listesi **hiç** gösterilmez. Güvenilir yol:

### A) Sunucuda SSH (en net)

Coolify’ın bağlı olduğu makinede:

```bash
docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}'
```

Postfix / Dovecot satırındaki **`Names`** sütunu = `JIR_CONTAINER_*` için yapıştıracağın tam ad.

Tek kaynak için konteyner içinden:

```bash
docker inspect "$(docker ps -q --filter ancestor=boky/postfix | head -1)" --format '{{.Name}}'
```

(imaj adını kendi Postfix imajınla değiştir)

### B) Coolify üzerinden

- **Docker Compose / Service Stack** kullanıyorsan: Projede ilgili **stack kaynağını** aç; Coolify genelde servisleri compose tanımından bilir ama **fiziksel konteyner adı** her zaman `docker ps` ile doğrulanmalıdır.
- Bazı sürümlerde **Server → Proxy / Docker** veya kaynak sayfasında **Logs / Terminal** üzerinden süreç görülür; tam ad yine SSH ile kesinleşir.

Bu isimleri bir sonraki adımda **Environment Variables** içine yazacaksın.

---

## 2) Ortam değişkenlerini nereye yazılır? (“Environment” alanı yokmuş gibi görünüyorsa)

Resmî Coolify dokümantasyonunda bunlar **kaynak (resource)** bazında **Environment Variables** altında toplanır; **Normal view** (kart kart) veya **Developer view** (`.env` metni) seçilebilir.

Tipik yol (metinler sürüme göre küçük farklılık gösterebilir):

1. Coolify ana sayfa → **Projects** → senin projen  
2. Ortam seç (**production** / **staging**)  
3. **Jîr-Mail Django panelinin** olduğu kaynağı aç — tek Dockerfile uygulaması veya compose içindeki `web` benzeri servis  
4. Kaynak sayfasında **Configuration / Settings** benzeri bölümde **Environment Variables** veya **Environment** sekmesi  
5. **Developer view** ile toplu yapıştırma en pratik: her satır `ANAHTAR=değer`

Eklemek istediğin örnekler (değerleri `docker ps` çıktına göre doldur):

| Değişken | Açıklama |
|----------|----------|
| `DATABASE_URL` | PostgreSQL bağlantısı (Coolify genelde bunu zaten üretir veya sen yapıştırırsın). |
| `JIR_CONTAINER_POSTFIX` | Postfix konteynerinin **tam adı**. |
| `JIR_CONTAINER_DOVECOT` | Dovecot konteynerinin **tam adı**. |
| `JIR_CONTAINER_POSTGRES` | Postgres konteyner adı (stack içindeyse). |
| `JIR_CONTAINER_REDIS` | Redis konteyner adı. |
| `DOCKER_HOST` | Docker API: genelde `unix:///var/run/docker.sock` **veya** Coolify’ın verdiği proxy adresi. Soket mount yoksa panel konteyner işlemleri çalışmaz. |
| `JIR_MANAGED_INSTALL` | Sadece Docker’ı **bilinçli olarak** devre dışı bırakmak için `1` (aksi halde boş bırak). |

**Paylaşılan değişkenler:** Coolify’da **Team / Project / Environment** için **Shared Variables** (dişli ikon) da vardır; kaynakta `{{project.VAR}}` ile kullanılabilir — bunlar ayrı bir sayfadır, tek tek uygulama kartında olması şart değildir. Detay: [Coolify Environment Variables](https://coolify.io/docs/knowledge-base/environment-variables).

**Öncelik:** Ortamda `JIR_CONTAINER_*` **tanımlıysa**, uygulama bunları veritabanındaki eski otomatik eşlemeden önce kullanır (güncel kod).

Kaydettikten sonra kaynak için **Restart / Redeploy** yap; değişiklik çalışan sürece ancak o zaman yansır.

---

## 3) Veritabanı ve otomatik eşleme (`docker_container_map`)

- Migrasyon: `python manage.py migrate` (özellikle `SystemConfig.docker_container_map` alanı için).
- Eski yanlış eşleme takılı kaldıysa PostgreSQL’de örnek temizlik:  
  `UPDATE saas_systemconfig SET docker_container_map = '{}'::jsonb;`  
  (Yedek al; tek satır config tablosu.)

---

## 4) API ile tanı (FULL admin oturumu)

1. Panele **FULL** yetkili admin ile giriş yap.
2. Tarayıcıda aç:  
   `https://<panel-domainin>/api/management/docker-diagnostics`
3. JSON’da kontrol et:
   - **`docker_ping`: true** → Django Docker’a ulaşıyor.
   - **`mail_related_containers`** → Her satırda **`network_ips`** (hangi Docker ağında, IP nedir).
   - **`mail_tcp`** → Panel sürecinin gördüğü **SMTP submission** ve **IMAP** host:port + TCP açık mı.
   - **`suggested_env_snippet`** → Coolify’a yapıştırmalık örnek `JIR_CONTAINER_*` blokları.
   - **`network_overlap_hint`** → Panel (`COOLIFY_CONTAINER_NAME`) ile postfix/dovecot ortak ağda mı.
   - **`merged_container_names`** → Panelin çözdüğü postfix/dovecot adları.
   - **`hint`** → Sunucunun ürettiği kısa yönlendirme metni.

**Kabuktan (SSH veya Coolify exec):**

```bash
python manage.py discover_mail_services
python manage.py discover_mail_services --json
```
---

## 5) Kurulum profili (Setup Wizard)

- **Coolify + `DATABASE_URL`:** Sihirbazda genelde **“Ortam veritabanı (DATABASE_URL)”** veya **“Manuel PostgreSQL”** uygun olur.
- **Tam Docker stack (tek host, soket mount):** “Docker ile tam kurulum” ancak Django’nun gerçekten o daemon’a eriştiği senaryolarda mantıklıdır.

Özet API: `GET /api/installer/bootstrap` → `install_modes`, `docker_available`, `has_database_url`.

---

## 6) Dovecot imajı (şablon + sırlar)

- Repoda yalnızca `dovecot/*.tpl` vardır; **`DB_*` ve `MAIL_DOMAIN`** konteyner ortamında zorunludur.
- `docker-compose.yml` içindeki dovecot servisinde `MAIL_DOMAIN` tanımlı olmalı (şablon `auth_default_realm` için).

---

## 7) Postfix + Dovecot’u otomatik YAML ile eklemek (Coolify)

Panel yalnızca Django iken mail servisleri yoksa, repodaki altyapı **harici PostgreSQL (`DATABASE_URL`)** ile Postfix+Dovecot için hazır bir **docker-compose** metni üretir:

```bash
# Panel konteynerinde veya .env yüklü ortamda
export MAIL_DOMAIN=jircode.com
export MAIL_STACK_DOCKER_NETWORK=coolify   # örnek — Postgres ile ortak ağ adı (`docker network ls`)
python manage.py provision_mail_stack --print-compose > mail-stack.yml
```

- Coolify’da bu dosyayı **ayrı bir Docker Compose resource** olarak ekleyip deploy et.
- Django uygulamasının env’sine üretilen YAML’daki gibi `JIR_CONTAINER_POSTFIX` / `JIR_CONTAINER_DOVECOT` yaz.
- **Önemli:** `DATABASE_URL` içindeki Postgres **hostname**’i (çoğu zaman konteyner adı), Postfix/Dovecot’un bağlı olduğu Docker ağından çözülebilir olmalı; değilse `MAIL_STACK_DOCKER_NETWORK` ile Postgres ile **aynı bridge**’i seç.

FULL oturumla API: `GET /api/management/mail-stack-compose` → JSON içinde `compose_yaml`.

Sunucuda Docker **soketi varsa** (panelde nadiren): `python manage.py provision_mail_stack --apply-docker` — konteynerleri doğrudan oluşturur/yeniler (**prod’da dikkat**).

---

## 8) Son doğrulama sırası

1. `docker-diagnostics`: ping + listede postfix/dovecot (veya env ile doğru `merged_container_names`).
2. Dashboard **Servis durumu**: yeşil / port veya Docker ile uyumlu.
3. **Başlat / Durdur** denemesi: “Container … not found” yok.
4. Test: bir mail hesabı ile IMAP/SMTP (veya uygulama içi test akışı).

---

## 9) Sık sorunlar

| Belirti | Olası neden |
|---------|-------------|
| `Container jir_postfix not found` | Env’de gerçek ad yok; Docker listesinde yok; yanlış daemon. |
| `docker_ping: false` | Soket mount / `DOCKER_HOST` yok veya yanlış. |
| `mail_related_containers` boş, ping true | Mail stack başka sunucuda veya başka Docker’da. |
| Env ekledim, hâlâ eski ad | Uygulama restart edilmedi veya DB’de eski `docker_container_map`. |
| Parola sızdı (geçmiş commit) | Veritabanı ve tüm servis parolalarını **rotate** et. |

---

## 10) İlgili dosyalar (kod tarafı)

- `config/settings.py` — `JIR_CONTAINER_*`, `DOCKER_HOST`
- `management/docker_containers.py` — çözüm sırası: `os.environ` → DB map → settings
- `management/api.py` — `docker-diagnostics`, servis durumu, konteyner aksiyonları
- `installer/mail_stack.py` — Coolify için compose üretimi / opsiyonel Docker kurulumu
- `dovecot/*.tpl` + `dovecot/Dockerfile` — entrypoint ile güvenli SQL ana yapılandırması

Bu listeyi her major Coolify / compose değişikliğinde baştan sona bir kez daha işlemek iyi pratik olur.
