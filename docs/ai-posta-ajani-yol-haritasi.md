# Jîr-Mail AI Posta Ajanı — Yol Haritası

> **Amaç:** E-postanın tamamını yapay zekanın yönetmesi — sınıflandırma, organize, yanıt, onay, VIP, özet.

**Güncelleme:** Telegram / WhatsApp bildirimleri **kapsam dışı** (şimdilik). Uygulama içi SSE + toast yeterli.

---

## Tamamlanan

| Faz | İçerik |
|-----|--------|
| **0** | Temel ajan: triage, organize, kurallar, digest, Celery, AI panel |
| **1** | Akıllı yanıt: draft, send, yanıt bekleyenler |
| **3** | Onay kuyruğu: `MailAiPendingAction`, onayla/reddet, assist modu |
| **4 (kısmi)** | VIP gönderenler: `MailVipSender`, triage önceliği |
| **UI v4** | Modern webmail: ajan komut çubuğu, onay sekmesi, kart tasarım |

---

## Faz 2 — Uygulama İçi Bildirim (Telegram yok)

| Görev | Durum |
|-------|--------|
| SSE `approval_update` | ✅ |
| Toast acil / onay bekleyen | ✅ (JS) |
| Ses / tarayıcı Notification API | ⏳ |
| Bildirim tercihleri (ayarlar) | ⏳ |

---

## Faz 3 — Onay Kuyruğu ✅

- Assist modunda spam/arşiv/taşıma → onay kuyruğu
- Otopilot: güvenli aksiyonlar direkt, riskliler kuyruk
- API: `GET /ai/approvals`, `POST …/approve`, `POST …/reject`
- UI: **Onay** sekmesi

---

## Faz 4 — VIP & Tehdit (devam)

| Görev | Durum |
|-------|--------|
| VIP liste CRUD | ✅ |
| Triage VIP → high priority | ✅ |
| Dolandırıcılık birleşik skor | ⏳ |
| Bounce AI özeti banner | ⏳ |
| 24 saat triage widget | ⏳ |

---

## Faz 5 — Tam Otonomi

- Kural önerisi (“3 kez arşivledin”)
- Zamanlanmış brifing saati (profilde var, UI iyileştirme)
- Audit log (AI IMAP/SMTP aksiyonları)
- API maliyet takibi

---

## Deploy

```bash
docker exec jir_django python manage.py migrate
docker compose restart django celery_worker celery_beat
```

Webmail cache: `?v=20260829e`

---

## Sıradaki adım

**Faz 4** tamamlama (tehdit skoru + bounce) ve **Faz 5** audit log.
