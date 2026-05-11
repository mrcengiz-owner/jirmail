# Uygulama Planı: Kurumsal UI Yeniden Tasarımı

## Genel Bakış

Bu plan, jir-mail projesinin kurumsal UI yeniden tasarımını adım adım hayata geçirir. Mevcut Django 5.2 + HTMX + Alpine.js stack'i korunarak Tailwind CSS CDN bağımlılığı kaldırılır, PostCSS tabanlı bir build pipeline kurulur, Flowbite entegre edilir ve tüm sayfalar WCAG 2.1 AA uyumlu, light/dark mode destekli, responsive bir yapıya kavuşturulur. Uygulama dili: **JavaScript** (frontend) ve **Python** (testler).

---

## Görevler

- [x] 1. Build Pipeline Kurulumu
  - [x] 1.1 `package.json` oluştur: `build`, `build:prod` ve `watch` script'lerini tanımla
    - `tailwindcss -i ./static/css/input.css -o ./static/css/main.css` komutunu kullan
    - `build:prod` için `NODE_ENV=production --minify` flag'i ekle
    - `tailwindcss` ve `flowbite` bağımlılıklarını `devDependencies`'e ekle
    - _Gereksinimler: 1.1, 1.2, 1.4_
  - [x] 1.2 `tailwind.config.js` oluştur: mevcut inline config'i dosyaya taşı
    - `content: ['./templates/**/*.html', './static/js/**/*.js']` ile PurgeCSS taramasını yapılandır
    - Mevcut `slate-850`, `emerald-400/500/600` ve `pulse-slow` animasyonunu koru
    - `darkMode: 'class'` ayarını ekle
    - `plugins: [require('flowbite/plugin')]` satırını ekle
    - _Gereksinimler: 1.3, 1.7, 2.1_
  - [x] 1.3 `postcss.config.js` oluştur: `tailwindcss` ve `autoprefixer` plugin'lerini yapılandır
    - _Gereksinimler: 1.1_
  - [x] 1.4 `static/css/input.css` oluştur: `@tailwind base`, `@tailwind components`, `@tailwind utilities` direktiflerini ekle; `[x-cloak]` ve `custom-scrollbar` gibi mevcut global stilleri buraya taşı
    - _Gereksinimler: 1.1, 12.3_

- [x] 2. Design Token Sistemi
  - [x] 2.1 `tailwind.config.js`'e semantik renk gruplarını ekle: `primary`, `secondary`, `success`, `warning`, `danger`, `neutral`
    - Her grup için `50`–`900` arası tüm shade değerlerini tanımla
    - `primary` grubunu mevcut `emerald` renkleriyle eşleştir
    - WCAG 2.1 AA (4.5:1) kontrast oranını karşılayan değerler seç
    - _Gereksinimler: 3.2, 3.6_
  - [x] 2.2 `tailwind.config.js`'e tipografi token'larını ekle
    - `fontFamily.sans: ['Inter', 'ui-sans-serif', 'system-ui']`
    - `fontFamily.mono: ['JetBrains Mono', 'ui-monospace', 'monospace']`
    - _Gereksinimler: 3.4_
  - [ ]* 2.3 Design Token shade bütünlüğü için property testi yaz (Hypothesis)
    - **Özellik 1: Design Token Shade Bütünlüğü**
    - `tailwind.config.js`'i parse et; her semantik renk grubu için 50–900 shade'lerinin varlığını doğrula
    - **Doğrular: Gereksinim 3.2**

- [x] 3. Flowbite Entegrasyonu
  - [x] 3.1 `npm install flowbite` ile Flowbite'ı kur; `tailwind.config.js` plugin kaydını doğrula
    - _Gereksinimler: 2.1_
  - [x] 3.2 `static/js/app.js`'e Flowbite başlatma kodunu ekle: Alpine.js `alpine:init` event'i tamamlandıktan sonra `initFlowbite()` çağır
    - HTMX `htmx:afterSwap` event'inde de `initFlowbite()` yeniden çağır (partial yüklemeler için)
    - _Gereksinimler: 2.4, 2.5, 12.4_
  - [ ]* 3.3 Alpine.js nitelik korunumu için property testi yaz (Hypothesis + Playwright)
    - **Özellik 12: Alpine.js Nitelik Korunumu**
    - Flowbite başlatması sonrasında `hx-*` ve `x-*` niteliklerinin DOM'da korunduğunu doğrula
    - **Doğrular: Gereksinim 2.4**

- [x] 4. `base.html` Refactor
  - [x] 4.1 `base.html`'den CDN script etiketlerini kaldır: `cdn.tailwindcss.com`, inline `tailwind.config = {...}` bloğunu sil
    - `<link rel="stylesheet" href="{% static 'css/main.css' %}">` ekle
    - Alpine.js CDN referansını `defer` niteliğiyle koru veya `static/js/app.js`'e taşı
    - _Gereksinimler: 1.6, 13.3_
  - [x] 4.2 `base.html`'e Theme Controller bloğunu ekle
    - `<html>` elementine `x-data` veya `x-bind:class` ile dark mode class bağlaması yap
    - FOUC önlemek için `<head>` içinde inline script ile `localStorage` değerini erken uygula
    - Sidebar veya header'a tema geçiş düğmesi (güneş/ay ikonu) ekle
    - _Gereksinimler: 4.1, 4.2, 4.7, 4.8_
  - [x] 4.3 `base.html`'deki HTMX hata handler'ını genişlet: 401/403/404/500 için Türkçe mesajlar ve `Alpine.store('toast').add(...)` çağrısı ekle
    - _Gereksinimler: 9.9_

- [x] 5. `static/js/app.js` Refactor
  - [x] 5.1 `Alpine.store('theme', {...})` store'unu yaz: `init()`, `toggle()`, `apply()` metodlarını implement et
    - `localStorage` erişim hatası için `try/catch` ile `prefers-color-scheme` fallback ekle
    - Geçersiz `localStorage` değeri için `'dark'` varsayılanına düş
    - _Gereksinimler: 4.1, 4.2, 4.3, 4.4_
  - [x] 5.2 `Alpine.store('toast', {...})` store'unu yaz: `notifications[]`, `add()`, `remove()` metodlarını implement et
    - `maxVisible: 5` sınırını uygula; 5'i aşan bildirimleri kuyruğa al
    - `setTimeout(() => this.remove(id), 5000)` ile otomatik kapanmayı implement et
    - 300ms animasyon süresi için `visible` flag'i kullan
    - _Gereksinimler: 11.3, 11.4, 11.5, 11.6_
  - [x] 5.3 Sidebar aktif state yönetimini implement et: `htmx:afterRequest` event'inde `[data-nav-item]` elementlerini güncelle
    - Tıklanan öğeye `aria-current="page"` ve `bg-primary-500/10 text-primary-400` sınıflarını ekle
    - Diğer öğelerden bu nitelikleri kaldır
    - _Gereksinimler: 9.1_
  - [ ]* 5.4 Tema kalıcılığı için property testi yaz (Hypothesis + Playwright)
    - **Özellik 3: Tema Kalıcılığı**
    - Herhangi bir başlangıç durumundan toggle sonrası `localStorage` ve `<html>` class tutarlılığını doğrula
    - **Doğrular: Gereksinim 4.1, 4.2**
  - [ ]* 5.5 localStorage önceliği için property testi yaz (Hypothesis + Playwright)
    - **Özellik 4: localStorage Önceliği**
    - `localStorage` değeri mevcutken `prefers-color-scheme`'in yok sayıldığını doğrula
    - **Doğrular: Gereksinim 4.4**

- [x] 6. Checkpoint — Build pipeline ve temel JS çalışıyor
  - `npm run build` komutunun sıfır çıkış koduyla tamamlandığını doğrula
  - `static/css/main.css` dosyasının oluşturulduğunu kontrol et
  - Tüm testlerin geçtiğini doğrula; sorular varsa kullanıcıya sor.

- [x] 7. `templates/login.html` Refactor
  - [x] 7.1 `login.html`'i `base.html`'i extend edecek şekilde yeniden yaz
    - Standalone `<!DOCTYPE html>` yapısını kaldır; `{% extends 'base.html' %}` ekle
    - CDN script etiketlerini ve inline `tailwind.config` bloğunu kaldır
    - `loginForm()` Alpine.js bileşenini `static/js/app.js`'e taşı
    - _Gereksinimler: 7.1, 7.2_
  - [x] 7.2 Login formuna light/dark mode uyumlu stiller uygula
    - Light modda beyaz/açık gri arka plan, dark modda koyu arka plan
    - `blue-600` renk referanslarını `primary-600` design token'ına dönüştür
    - `autocomplete="username"` ve `autocomplete="current-password"` niteliklerini ekle
    - _Gereksinimler: 7.2, 7.6_
  - [x] 7.3 Login formuna 10 saniyelik timeout implement et
    - `AbortController` ile API isteğini iptal et
    - Timeout sonrası "Bağlantı zaman aşımına uğradı, lütfen tekrar deneyin." mesajını `role="alert"` ile göster
    - Hata mesajı elementine `role="alert"` niteliği ekle
    - _Gereksinimler: 7.3, 7.4, 7.5_

- [x] 8. `templates/setup.html` Refactor
  - [x] 8.1 `setup.html`'i `base.html`'i extend edecek şekilde yeniden yaz
    - Standalone yapıyı kaldır; `{% extends 'base.html' %}` ekle
    - `setupWizard()` Alpine.js bileşenini `static/js/app.js`'e taşı
    - _Gereksinimler: 8.8, 8.9_
  - [x] 8.2 Stepper bileşenini iyileştir: aktif (vurgulu), tamamlanan (onay ikonu) ve pasif adım görünümlerini implement et
    - `currentStep` ve `completedSteps[]` state'ini kullan
    - Her adım geçişinde stepper'ı güncelle
    - _Gereksinimler: 8.1, 8.3_
  - [x] 8.3 Form validasyonunu implement et: zorunlu alan kontrolü, e-posta format doğrulaması, şifre uzunluk kontrolü
    - Hata mesajlarını `role="alert"` ile ilgili alanın altında göster
    - PostgreSQL seçildiğinde ek alanları göster/gizle
    - _Gereksinimler: 8.4, 8.5, 8.6, 8.7_
  - [ ]* 8.4 Setup Wizard adım durumu tutarlılığı için property testi yaz (Hypothesis + Playwright)
    - **Özellik 13: Setup Wizard Adım Durumu Tutarlılığı**
    - 1–5 arası herhangi bir adımda aktif=1, tamamlanan=currentStep-1, pasif=totalSteps-currentStep olduğunu doğrula
    - **Doğrular: Gereksinim 8.1, 8.3**

- [x] 9. `templates/partials/sidebar.html` Refactor
  - [x] 9.1 Tüm nav öğelerine `data-nav-item` niteliği ekle; aktif state için `aria-current="page"` ve `bg-primary-500/10 text-primary-400` sınıflarını uygula
    - Pasif öğelerden bu sınıfları kaldır
    - Navigasyon gruplarını `<span>` başlıklarıyla (`Overview`, `Mail System`, `Management`) işaretle
    - _Gereksinimler: 9.1, 9.2_
  - [x] 9.2 Responsive hamburger menü desteği ekle
    - 768px altında sidebar'ı `transform: translateX(-100%)` ile gizle
    - `base.html`'deki hamburger düğmesiyle `Alpine.store` veya `x-data` üzerinden sidebar açma/kapama bağlantısını kur
    - Sidebar açıkken overlay (backdrop) render et; overlay'e tıklandığında sidebar kapansın
    - _Gereksinimler: 5.2_
  - [ ]* 9.3 Sidebar tekil aktif state için property testi yaz (Hypothesis + Playwright)
    - **Özellik 8: Sidebar Tekil Aktif State**
    - Herhangi bir nav öğesine tıklandığında `aria-current="page"` sayısının tam olarak 1 olduğunu doğrula
    - **Doğrular: Gereksinim 9.1**

- [x] 10. `templates/partials/toast.html` Refactor
  - [x] 10.1 Toast container'ını sağ alt köşeye taşı: `fixed bottom-4 right-4 z-[9999]`
    - `Alpine.store('toast').notifications` üzerinden `x-for` ile toast listesini render et
    - Her toast için `x-show` ve `x-transition` ile slide-in/fade-out animasyonu ekle (≤300ms)
    - _Gereksinimler: 11.2, 11.6_
  - [x] 10.2 Toast türlerine göre renk ve ikon eşlemesini implement et
    - `success`: yeşil + onay ikonu, `error`: kırmızı + çarpı ikonu, `warning`: sarı + uyarı ikonu, `info`: mavi + bilgi ikonu
    - `role="status"` ve `aria-live="polite"` ekle; `error` türü için `aria-live="assertive"` kullan
    - Kapat düğmesine (`×`) `@click="$store.toast.remove(notification.id)"` bağla
    - _Gereksinimler: 11.1, 11.4, 11.7_
  - [ ]* 10.3 Toast tür-renk tutarlılığı için property testi yaz (Hypothesis + Playwright)
    - **Özellik 9: Toast Tür-Renk Tutarlılığı**
    - Her toast türü için render edilen CSS sınıflarının tür-renk eşlemesiyle tutarlı olduğunu doğrula
    - **Doğrular: Gereksinim 11.1**
  - [ ]* 10.4 Toast maksimum görünür sayı için property testi yaz (Hypothesis + Playwright)
    - **Özellik 10: Toast Maksimum Görünür Sayı**
    - 1–10 arası toast gösteriminde aynı anda görünür sayının 5'i aşmadığını doğrula
    - **Doğrular: Gereksinim 11.5**

- [x] 11. Checkpoint — Temel bileşenler tamamlandı
  - Tüm testlerin geçtiğini doğrula; sorular varsa kullanıcıya sor.

- [x] 12. `templates/master_panel.html` ve Partial'lar Refactor
  - [x] 12.1 `master_panel.html`'i `base.html`'i extend edecek şekilde güncelle; `masterPanel()` Alpine.js bileşenini `static/js/app.js`'e taşı
    - HTMX spinner (`animate-spin`) için `htmx-indicator` sınıfını yapılandır
    - _Gereksinimler: 9.9_
  - [x] 12.2 `partials/dashboard.html`'i güncelle: aktif hesap, domain sayısı, disk kullanımı ve servis durumu kartlarını design token renkleriyle render et
    - Hardcoded renk değerlerini (`#1a2234` vb.) design token sınıflarıyla değiştir
    - _Gereksinimler: 9.3, 12.1_
  - [x] 12.3 `partials/accounts.html`'i güncelle: arama/filtreleme ve sayfalama destekli tablo; sıfır sonuç mesajı ekle
    - _Gereksinimler: 9.4, 12.1_
  - [x] 12.4 `partials/domains.html`'i güncelle: DNS doğrulama durumu için renk kodlu rozet (badge) ekle
    - _Gereksinimler: 9.5, 12.1_
  - [x] 12.5 `partials/backup.html`, `partials/logs.html`, `partials/containers.html`'i güncelle: design token sınıflarını uygula, container durum rozetlerini ekle
    - _Gereksinimler: 9.6, 9.7, 9.8, 12.1_
  - [ ]* 12.6 HTMX partial tema uyumu için property testi yaz (Hypothesis + Playwright)
    - **Özellik 11: HTMX Partial Tema Uyumu**
    - Herhangi bir tema durumunda HTMX ile yüklenen partial'ların `<html>` dark class'ını miras aldığını doğrula
    - **Doğrular: Gereksinim 12.2**

- [x] 13. `templates/mail_panel.html` Refactor
  - [x] 13.1 `mail_panel.html`'i `base.html`'i extend edecek şekilde güncelle; `mailApp()` Alpine.js bileşenini `static/js/app.js`'e taşı
    - 3 sütunlu düzeni implement et: klasör listesi (~20%), e-posta listesi (~35%), içerik (~45%)
    - _Gereksinimler: 10.1_
  - [x] 13.2 Okunmamış e-posta rozeti ve okundu/okunmadı görsel ayrımını implement et
    - Okunmamış: `font-semibold` + farklı arka plan; okunmuş: `font-normal`
    - E-posta seçildiğinde `unread` durumunu `false` yap ve rozet sayacını azalt
    - _Gereksinimler: 10.2, 10.3, 10.4, 10.5_
  - [x] 13.3 Mobil tek sütunlu navigasyonu implement et: klasör → e-posta listesi → içerik geçişleri ve `←` geri düğmeleri
    - _Gereksinimler: 10.6, 5.4_
  - [ ]* 13.4 Mail okunmamış sayaç tutarlılığı için property testi yaz (Hypothesis + Playwright)
    - **Özellik 14: Mail Okunmamış Sayaç Tutarlılığı**
    - Herhangi bir okunmamış e-posta seçildiğinde rozet sayacının tam olarak 1 azaldığını doğrula
    - **Doğrular: Gereksinim 10.3**

- [x] 14. Responsive Tasarım
  - [x] 14.1 Tüm sayfalarda `overflow-x-hidden` uygula; 320px viewport'ta yatay scroll olmadığını doğrula
    - _Gereksinimler: 5.1, 5.6_
  - [x] 14.2 Mobil breakpoint'lerde (`md:` prefix) grid düzenlerini tek sütuna geçir: `master_panel.html` kartları ve tabloları
    - _Gereksinimler: 5.3_
  - [x] 14.3 Tüm tıklanabilir öğelerin (`button`, `a`, `[role="button"]`) mobil viewport'ta minimum 44×44px dokunma hedefi boyutuna sahip olmasını sağla
    - _Gereksinimler: 5.5_
  - [ ]* 14.4 Responsive overflow yok için property testi yaz (Hypothesis + Playwright)
    - **Özellik 5: Responsive Overflow Yok**
    - 320px–2560px arası viewport genişliklerinde yatay scroll olmadığını doğrula
    - **Doğrular: Gereksinim 5.1, 5.6**
  - [ ]* 14.5 Mobil dokunma hedefi boyutu için property testi yaz (Hypothesis + Playwright)
    - **Özellik 6: Mobil Dokunma Hedefi Boyutu**
    - 768px altı viewport'ta tüm tıklanabilir elementlerin ≥44×44px olduğunu doğrula
    - **Doğrular: Gereksinim 5.5**

- [x] 15. Erişilebilirlik (WCAG 2.1 AA)
  - [x] 15.1 Tüm etkileşimli elementlere (`button`, `input`, `a`, `select`) `aria-label` veya ilişkilendirilmiş `<label>` ekle; placeholder'ı tek başına etiket olarak kullanma
    - _Gereksinimler: 6.1, 6.7_
  - [x] 15.2 Focus trap implement et: modal ve dropdown açıldığında odağı içeride tut; Escape ile kapat ve odağı tetikleyiciye döndür
    - _Gereksinimler: 6.6_
  - [x] 15.3 `prefers-reduced-motion: reduce` medya sorgusunu `input.css`'e ekle: tüm `transition` ve `animation` sürelerini 0ms'ye indir
    - _Gereksinimler: 6.8_
  - [x] 15.4 Durum bilgisini (hata, uyarı, başarı) renk + ikon + metin kombinasyonuyla ilet; renk kaldırıldığında bilgi kaybı olmamasını sağla
    - _Gereksinimler: 6.5_
  - [ ]* 15.5 ARIA etiket bütünlüğü için property testi yaz (Hypothesis + Playwright)
    - **Özellik 7: ARIA Etiket Bütünlüğü**
    - Tüm etkileşimli elementlerin görünür metin, `aria-label`, `aria-labelledby` veya `<label>`'dan en az birine sahip olduğunu doğrula
    - **Doğrular: Gereksinim 6.1, 6.7**
  - [ ]* 15.6 WCAG kontrast uyumu için property testi yaz (Hypothesis + wcag-contrast)
    - **Özellik 2: WCAG Kontrast Uyumu**
    - Her semantik renk grubundaki metin/arka plan kombinasyonlarının ≥4.5:1 kontrast oranına sahip olduğunu doğrula
    - **Doğrular: Gereksinim 3.6, 6.3**

- [x] 16. Checkpoint — Tüm sayfalar ve erişilebilirlik tamamlandı
  - Tüm testlerin geçtiğini doğrula; sorular varsa kullanıcıya sor.

- [x] 17. `Dockerfile` Güncelleme
  - [x] 17.1 Dockerfile'a Node.js kurulum adımı ekle: `apt-get install -y nodejs npm` veya `curl -fsSL https://deb.nodesource.com/setup_20.x | bash -`
    - _Gereksinimler: 13.4_
  - [x] 17.2 Dockerfile'a `RUN npm ci && npm run build` adımını ekle: `COPY . .` satırından sonra, `collectstatic` öncesinde çalışacak şekilde yerleştir
    - _Gereksinimler: 13.4, 13.5_

---

## Notlar

- `*` ile işaretli alt görevler isteğe bağlıdır; MVP için atlanabilir
- Her görev, izlenebilirlik için ilgili gereksinimlere referans verir
- Checkpoint görevleri artımlı doğrulama sağlar
- Property testleri evrensel doğruluk özelliklerini, birim testleri belirli örnekleri ve edge case'leri doğrular
- Tüm property testleri minimum 100 iterasyon çalıştırılmalıdır (`@settings(max_examples=100)`)
- Test etiket formatı: `# Feature: corporate-ui-redesign, Property {N}: {property_text}`

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2", "1.3", "1.4"] },
    { "id": 1, "tasks": ["2.1", "2.2", "3.1"] },
    { "id": 2, "tasks": ["2.3", "3.2"] },
    { "id": 3, "tasks": ["3.3", "4.1", "4.2", "4.3"] },
    { "id": 4, "tasks": ["5.1", "5.2", "5.3"] },
    { "id": 5, "tasks": ["5.4", "5.5", "7.1", "8.1"] },
    { "id": 6, "tasks": ["7.2", "7.3", "8.2", "8.3", "9.1", "9.2", "10.1", "10.2"] },
    { "id": 7, "tasks": ["8.4", "9.3", "10.3", "10.4", "12.1", "13.1"] },
    { "id": 8, "tasks": ["12.2", "12.3", "12.4", "12.5", "13.2", "13.3"] },
    { "id": 9, "tasks": ["12.6", "13.4", "14.1", "14.2", "14.3"] },
    { "id": 10, "tasks": ["14.4", "14.5", "15.1", "15.2", "15.3", "15.4"] },
    { "id": 11, "tasks": ["15.5", "15.6", "17.1"] },
    { "id": 12, "tasks": ["17.2"] }
  ]
}
```
