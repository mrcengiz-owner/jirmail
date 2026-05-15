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

## 1) Coolify’da gerçek konteyner adlarını bul

1. Coolify → ilgili **proje** → **Resources / Containers** (veya servis detayı).
2. Postfix, Dovecot, Postgres, Redis satırlarındaki **tam konteyner adını** kopyala (ör. `abc123-postfix-xyz`).
3. İstersen sunucuda SSH ile: `docker ps --format '{{.Names}}'` ile aynı listeyi doğrula.

Bu isimler bir sonraki adımda **ortam değişkeni** olarak kullanılacak.

---

## 2) Django (panel) servisine ortam değişkenleri

Coolify’da **Django’nun çalıştığı** uygulamanın Environment bölümüne ekle (değerleri kendi adlarınla değiştir):

| Değişken | Açıklama |
|----------|----------|
| `DATABASE_URL` | PostgreSQL bağlantısı (Coolify genelde bunu zaten üretir veya sen yapıştırırsın). |
| `JIR_CONTAINER_POSTFIX` | Postfix konteynerinin **tam adı**. |
| `JIR_CONTAINER_DOVECOT` | Dovecot konteynerinin **tam adı**. |
| `JIR_CONTAINER_POSTGRES` | Postgres konteyner adı (stack içindeyse). |
| `JIR_CONTAINER_REDIS` | Redis konteyner adı. |
| `DOCKER_HOST` | Docker API: genelde `unix:///var/run/docker.sock` **veya** Coolify’ın verdiği proxy adresi. Soket mount yoksa panel konteyner işlemleri çalışmaz. |
| `JIR_MANAGED_INSTALL` | Sadece Docker’ı **bilinçli olarak** devre dışı bırakmak için `1` (aksi halde boş bırak). |

**Öncelik:** Ortamda `JIR_CONTAINER_*` **tanımlıysa**, uygulama bunları veritabanındaki eski otomatik eşlemeden önce kullanır (güncel kod).

Deploy / **Redeploy** sonrası process env güncellenir; değiştirdikten sonra servisi yeniden başlat.

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
   - **`mail_related_containers`** → Postfix/Dovecot burada görünmüyorsa, ya isimler farklıdır ya da **bu Docker listesinde** mail konteyneri yoktur (başka host / farklı daemon).
   - **`merged_container_names`** → Panelin çözdüğü postfix/dovecot adları.
   - **`hint`** → Sunucunun ürettiği kısa yönlendirme metni.

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

## 7) Son doğrulama sırası

1. `docker-diagnostics`: ping + listede postfix/dovecot (veya env ile doğru `merged_container_names`).
2. Dashboard **Servis durumu**: yeşil / port veya Docker ile uyumlu.
3. **Başlat / Durdur** denemesi: “Container … not found” yok.
4. Test: bir mail hesabı ile IMAP/SMTP (veya uygulama içi test akışı).

---

## 8) Sık sorunlar

| Belirti | Olası neden |
|---------|-------------|
| `Container jir_postfix not found` | Env’de gerçek ad yok; Docker listesinde yok; yanlış daemon. |
| `docker_ping: false` | Soket mount / `DOCKER_HOST` yok veya yanlış. |
| `mail_related_containers` boş, ping true | Mail stack başka sunucuda veya başka Docker’da. |
| Env ekledim, hâlâ eski ad | Uygulama restart edilmedi veya DB’de eski `docker_container_map`. |
| Parola sızdı (geçmiş commit) | Veritabanı ve tüm servis parolalarını **rotate** et. |

---

## 9) İlgili dosyalar (kod tarafı)

- `config/settings.py` — `JIR_CONTAINER_*`, `DOCKER_HOST`
- `management/docker_containers.py` — çözüm sırası: `os.environ` → DB map → settings
- `management/api.py` — `docker-diagnostics`, servis durumu, konteyner aksiyonları
- `installer/profiles.py` — kurulum profilleri (docker_stack / platform_env / platform_manual)
- `dovecot/*.tpl` + `dovecot/Dockerfile` — entrypoint ile güvenli SQL ana yapılandırması

Bu listeyi her major Coolify / compose değişikliğinde baştan sona bir kez daha işlemek iyi pratik olur.
