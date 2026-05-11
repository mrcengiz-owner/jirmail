# Tasarım Belgesi: Kurumsal UI Yeniden Tasarımı

## Genel Bakış

Bu belge, jir-mail projesinin kurumsal UI yeniden tasarımı için teknik mimariyi tanımlar. Mevcut Django 5.2 + HTMX + Alpine.js stack'i korunarak Tailwind CSS CDN bağımlılığı kaldırılacak, yerine PostCSS tabanlı bir build pipeline kurulacaktır. Flowbite component library entegre edilecek, merkezi bir design token sistemi oluşturulacak ve tüm sayfalar WCAG 2.1 AA uyumlu, light/dark mode destekli, responsive bir yapıya kavuşturulacaktır.

### Mevcut Durum Analizi

| Sorun | Mevcut Durum | Hedef Durum |
|-------|-------------|-------------|
| CSS Build | CDN (cdn.tailwindcss.com) | PostCSS + Tailwind v3 yerel build |
| Template Tutarlılığı | login/setup standalone, base.html extend etmiyor | Tüm sayfalar base.html extend eder |
| Renk Tutarsızlığı | login: blue-600, setup: emerald, panel: emerald | Merkezi design token sistemi |
| Tema Desteği | Sadece dark mode | Light/dark mode + localStorage kalıcılığı |
| Toast Konumu | Sağ üst (top-6 right-6) | Sağ alt (bottom-4 right-4) |
| Sidebar Aktif State | Yok | aria-current="page" + görsel vurgu |
| Responsive | Hamburger menü yok | Tam responsive, 320px-2560px |

---

## Mimari

### Yüksek Seviye Mimari

```
┌─────────────────────────────────────────────────────────────┐
│                     Build Pipeline                          │
│  tailwind.config.js ──► PostCSS ──► static/css/main.css    │
│  (Design Tokens)         (PurgeCSS)   (Minified)            │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    Template Katmanı                         │
│                                                             │
│  base.html (Theme Controller + compiled CSS)                │
│    ├── login.html (extends base.html)                       │
│    ├── setup.html (extends base.html)                       │
│    ├── master_panel.html (extends base.html)                │
│    │     └── partials/sidebar.html (aktif state)            │
│    │     └── partials/toast.html (sağ alt, stacking)        │
│    └── mail_panel.html (extends base.html)                  │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                  Alpine.js Katmanı                          │
│  Alpine.store('theme') ── Theme Controller                  │
│  loginForm() ── Login bileşeni                              │
│  setupWizard() ── Setup sihirbazı                           │
│  masterPanel() ── Master panel                              │
│  mailApp() ── Mail panel                                    │
│  toastManager() ── Toast stacking yöneticisi                │
└─────────────────────────────────────────────────────────────┘
```

### Teknoloji Kararları

**Tailwind v3 (v4 değil):** Mevcut `tailwind.config.js` inline yapısı v3 sözdizimini kullanmaktadır. v4 breaking changes içermekte ve Flowbite ile uyumluluğu henüz tam değildir. v3 korunacaktır.

**Flowbite (DaisyUI yerine):** Flowbite, Tailwind CSS eklentisi olarak çalışır ve Alpine.js ile doğal uyum sağlar. DaisyUI CSS değişken sistemi Alpine.js reaktivitesiyle çakışma riski taşır. Flowbite'ın JavaScript başlatması Alpine.js `init` yaşam döngüsüne entegre edilebilir. Ayrıca Flowbite, HTMX ile yüklenen partial'larda yeniden başlatma için `htmx:afterSwap` event'ini destekler.

**PostCSS + Tailwind CLI:** Vite yerine daha basit bir araç zinciri tercih edilmiştir. Django'nun `collectstatic` akışıyla doğrudan uyumludur ve ek bundler karmaşıklığı gerektirmez.

---

## Bileşenler ve Arayüzler

### 1. Build Pipeline

```
proje_kökü/
├── package.json              # npm scripts: build, watch, build:prod
├── tailwind.config.js        # Design tokens + Flowbite plugin
├── postcss.config.js         # PostCSS konfigürasyonu
├── static/
│   ├── css/
│   │   ├── input.css         # Tailwind direktifleri (@tailwind base/components/utilities)
│   │   └── main.css          # Derlenen çıktı (gitignore'da)
│   └── js/
│       └── app.js            # Alpine.js bileşenleri
└── templates/                # PurgeCSS content tarama hedefi
```

**package.json scripts:**
```json
{
  "scripts": {
    "build": "tailwindcss -i ./static/css/input.css -o ./static/css/main.css",
    "build:prod": "NODE_ENV=production tailwindcss -i ./static/css/input.css -o ./static/css/main.css --minify",
    "watch": "tailwindcss -i ./static/css/input.css -o ./static/css/main.css --watch"
  }
}
```

### 2. Design Token Sistemi

`tailwind.config.js` merkezi token deposu olarak görev yapar:

```javascript
module.exports = {
  darkMode: 'class',
  content: ['./templates/**/*.html', './static/js/**/*.js'],
  theme: {
    extend: {
      colors: {
        // Mevcut renkler korunur
        slate: { 850: '#1a2234' },
        // Semantik renk grupları
        primary: {
          50: '#f0fdf4', 100: '#dcfce7', 200: '#bbf7d0',
          300: '#86efac', 400: '#34d399', 500: '#10b981',
          600: '#059669', 700: '#047857', 800: '#065f46', 900: '#064e3b'
        },
        secondary: { /* slate tabanlı */ },
        success: { /* emerald tabanlı */ },
        warning: { /* amber tabanlı */ },
        danger: { /* red tabanlı */ },
        neutral: { /* slate tabanlı */ }
      },
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui'],
        mono: ['JetBrains Mono', 'ui-monospace', 'monospace']
      },
      animation: {
        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite'
      }
    }
  },
  plugins: [require('flowbite/plugin')]
}
```

### 3. Theme Controller (Alpine.js Store)

`static/js/app.js` içinde tanımlanır:

```javascript
document.addEventListener('alpine:init', () => {
  Alpine.store('theme', {
    current: 'dark',
    
    init() {
      const saved = localStorage.getItem('theme');
      if (saved) {
        this.current = saved;
      } else {
        this.current = window.matchMedia('(prefers-color-scheme: dark)').matches 
          ? 'dark' : 'light';
      }
      this.apply();
    },
    
    toggle() {
      this.current = this.current === 'dark' ? 'light' : 'dark';
      localStorage.setItem('theme', this.current);
      this.apply();
    },
    
    apply() {
      if (this.current === 'dark') {
        document.documentElement.classList.add('dark');
      } else {
        document.documentElement.classList.remove('dark');
      }
    }
  });
});
```

**Kritik:** Theme store `init()` metodu `alpine:init` event'inde çalışır. Bu, Alpine.js başlamadan önce `<html>` elementine `dark` class'ının uygulanmasını sağlar ve FOUC (Flash of Unstyled Content) önler.

### 4. Toast Manager (Stacking Desteği)

Mevcut tek toast bileşeni, stacking destekli bir yöneticiye dönüştürülür:

```javascript
Alpine.store('toast', {
  notifications: [],
  maxVisible: 5,
  
  add(message, type = 'success') {
    const id = Date.now();
    const notification = { id, message, type, visible: true };
    
    if (this.notifications.filter(n => n.visible).length >= this.maxVisible) {
      // Kuyruğa al - en eski görünür bildirimi gizle
      const oldest = this.notifications.find(n => n.visible);
      if (oldest) oldest.visible = false;
    }
    
    this.notifications.push(notification);
    
    setTimeout(() => this.remove(id), 5000);
  },
  
  remove(id) {
    const notification = this.notifications.find(n => n.id === id);
    if (notification) notification.visible = false;
    setTimeout(() => {
      this.notifications = this.notifications.filter(n => n.id !== id);
    }, 300); // Animasyon süresi
  }
});
```

### 5. Sidebar Aktif State Yönetimi

HTMX tab yüklemelerinde aktif state'i yönetmek için `htmx:afterRequest` event'i kullanılır:

```javascript
document.addEventListener('htmx:afterRequest', (event) => {
  const trigger = event.detail.elt;
  if (trigger.dataset.navItem) {
    // Tüm nav öğelerinden aktif state kaldır
    document.querySelectorAll('[data-nav-item]').forEach(el => {
      el.removeAttribute('aria-current');
      el.classList.remove('bg-primary-500/10', 'text-primary-400');
    });
    // Tıklanan öğeye aktif state ekle
    trigger.setAttribute('aria-current', 'page');
    trigger.classList.add('bg-primary-500/10', 'text-primary-400');
  }
});
```

---

## Veri Modelleri

### Theme State

```typescript
interface ThemeState {
  current: 'light' | 'dark';
  // localStorage key: 'theme'
  // html class: 'dark' (dark mode) veya '' (light mode)
}
```

### Toast Notification

```typescript
interface ToastNotification {
  id: number;           // Date.now() ile üretilen benzersiz ID
  message: string;      // Gösterilecek mesaj
  type: 'success' | 'error' | 'warning' | 'info';
  visible: boolean;     // Görünürlük durumu (animasyon için)
}

interface ToastStore {
  notifications: ToastNotification[];
  maxVisible: 5;        // Sabit maksimum görünür bildirim sayısı
}
```

### Sidebar Navigation Item

```typescript
interface NavItem {
  label: string;
  icon: string;         // SVG path
  htmxEndpoint: string; // hx-get değeri
  group: 'overview' | 'mail-system' | 'management';
  isActive: boolean;    // aria-current="page" durumu
}
```

### Setup Wizard State

```typescript
interface SetupWizardState {
  currentStep: number;  // 1-5
  totalSteps: 5;
  completedSteps: number[]; // Tamamlanan adım numaraları
  // Her adım için form verileri
  domain: string;
  adminEmail: string;
  adminPassword: string;
  dbType: 'sqlite' | 'postgresql';
  // PostgreSQL için ek alanlar
  dbHost?: string;
  dbPort?: number;
  dbName?: string;
  dbUser?: string;
  dbPassword?: string;
}
```

---

## Doğruluk Özellikleri

*Bir özellik (property), bir sistemin tüm geçerli çalışmalarında doğru olması gereken bir karakteristik veya davranıştır — temelde sistemin ne yapması gerektiğine dair biçimsel bir ifadedir. Özellikler, insan tarafından okunabilir spesifikasyonlar ile makine tarafından doğrulanabilir doğruluk garantileri arasındaki köprü görevi görür.*

### Özellik 1: Design Token Shade Bütünlüğü

*Her* semantik renk grubu (`primary`, `secondary`, `success`, `warning`, `danger`, `neutral`) için `tailwind.config.js` içinde 50'den 900'e kadar tüm shade değerlerinin tanımlı olması gerekir.

**Doğrular: Gereksinim 3.2**

---

### Özellik 2: WCAG Kontrast Uyumu

*Her* semantik renk grubundaki metin rengi ve arka plan rengi kombinasyonu için hesaplanan WCAG 2.1 kontrast oranı 4.5:1'den büyük veya eşit olmalıdır.

**Doğrular: Gereksinim 3.6, 6.3**

---

### Özellik 3: Tema Kalıcılığı

*Herhangi bir* başlangıç tema durumundan (`light` veya `dark`) tema geçiş düğmesine tıklandığında, `localStorage.getItem('theme')` değeri yeni temayı yansıtmalı ve `<html>` elementinin `dark` class durumu bu değerle tutarlı olmalıdır.

**Doğrular: Gereksinim 4.1, 4.2**

---

### Özellik 4: localStorage Önceliği

*Herhangi bir* `localStorage` tema değeri (`light` veya `dark`) mevcutken, sistem `prefers-color-scheme` tercihi ne olursa olsun `<html>` elementinin `dark` class durumu `localStorage` değerini yansıtmalıdır.

**Doğrular: Gereksinim 4.4**

---

### Özellik 5: Responsive Overflow Yok

*320px ile 2560px arasındaki herhangi bir* viewport genişliğinde, sayfadaki hiçbir element `document.body`'nin genişliğini aşmamalı ve yatay scroll bar oluşmamalıdır.

**Doğrular: Gereksinim 5.1, 5.6**

---

### Özellik 6: Mobil Dokunma Hedefi Boyutu

*Mobil viewport'ta (768px altı) herhangi bir* tıklanabilir element (`button`, `a`, `[role="button"]`) için `getBoundingClientRect()` ile ölçülen genişlik ve yükseklik değerlerinin her ikisi de 44px'den büyük veya eşit olmalıdır.

**Doğrular: Gereksinim 5.5**

---

### Özellik 7: ARIA Etiket Bütünlüğü

*Herhangi bir* etkileşimli element (`button`, `input`, `a`, `select`) için görünür metin içeriği, `aria-label`, `aria-labelledby` veya ilişkilendirilmiş `<label>` niteliklerinden en az biri mevcut olmalıdır.

**Doğrular: Gereksinim 6.1, 6.7**

---

### Özellik 8: Sidebar Tekil Aktif State

*Herhangi bir* sidebar navigasyon öğesine tıklandığında, `aria-current="page"` niteliğine sahip öğe sayısı tam olarak 1 olmalı ve bu nitelik yalnızca tıklanan öğede bulunmalıdır.

**Doğrular: Gereksinim 9.1**

---

### Özellik 9: Toast Tür-Renk Tutarlılığı

*Herhangi bir* toast türü (`success`, `error`, `warning`, `info`) için `notify` event'i tetiklendiğinde, DOM'da render edilen toast elementinin CSS sınıfları o türe karşılık gelen renk ve ikon ile tutarlı olmalıdır.

**Doğrular: Gereksinim 11.1**

---

### Özellik 10: Toast Maksimum Görünür Sayı

*1 ile 10 arasında herhangi bir* sayıda toast bildirimi art arda gösterildiğinde, aynı anda DOM'da görünür olan toast sayısı hiçbir zaman 5'i aşmamalıdır.

**Doğrular: Gereksinim 11.5**

---

### Özellik 11: HTMX Partial Tema Uyumu

*Herhangi bir* tema durumunda (`light` veya `dark`) HTMX ile yüklenen partial template'ler, `<html>` elementindeki `dark` class durumunu miras alarak doğru tema renklerini uygulamalıdır; partial yüklenmesi tema geçişi gerektirmemelidir.

**Doğrular: Gereksinim 12.2**

---

### Özellik 12: Alpine.js Nitelik Korunumu

*Herhangi bir* DOM elementinde `hx-*` ve `x-*` nitelikleri birlikte kullanıldığında, Flowbite başlatması sonrasında bu niteliklerin tamamı DOM'da korunmalı ve hiçbiri kaldırılmamalıdır.

**Doğrular: Gereksinim 2.4**

---

### Özellik 13: Setup Wizard Adım Durumu Tutarlılığı

*Herhangi bir* adım numarasında (`1`-`5`) Setup Wizard render edildiğinde, stepper bileşeninde aktif adım sayısı tam olarak 1, tamamlanan adım sayısı `currentStep - 1` ve pasif adım sayısı `totalSteps - currentStep` olmalıdır.

**Doğrular: Gereksinim 8.1, 8.3**

---

### Özellik 14: Mail Okunmamış Sayaç Tutarlılığı

*Herhangi bir* okunmamış e-posta seçildiğinde, ilgili klasörün okunmamış rozet sayacı tam olarak 1 azalmalı ve seçilen e-postanın `unread` durumu `false` olarak güncellenmelidir.

**Doğrular: Gereksinim 10.3**

---

## Hata Yönetimi

### Build Pipeline Hataları

| Hata Senaryosu | Davranış |
|---------------|----------|
| Geçersiz `tailwind.config.js` sözdizimi | Non-zero exit code, stderr'e hata mesajı |
| `static/css/input.css` bulunamadı | Non-zero exit code, dosya yolu hata mesajı |
| Disk yazma izni yok | Non-zero exit code, permission error mesajı |
| `npm run build` 60 saniyeyi aşarsa | Timeout, non-zero exit code |

### Theme Controller Hataları

| Hata Senaryosu | Davranış |
|---------------|----------|
| `localStorage` erişim engeli (private browsing) | `try/catch` ile yakalanır, `prefers-color-scheme` fallback kullanılır |
| Geçersiz `localStorage` değeri | `'dark'` varsayılan değerine düşülür |

### HTMX İstek Hataları

Mevcut `htmx:responseError` handler korunur ve genişletilir:

```javascript
document.addEventListener('htmx:responseError', (event) => {
  const status = event.detail.xhr.status;
  const messages = {
    401: 'Oturum süresi doldu. Lütfen tekrar giriş yapın.',
    403: 'Bu işlem için yetkiniz yok.',
    404: 'İstenen içerik bulunamadı.',
    500: 'Sunucu hatası. Lütfen daha sonra tekrar deneyin.',
    0: 'Bağlantı hatası. Ağ bağlantınızı kontrol edin.'
  };
  
  const message = messages[status] || `Beklenmeyen hata (${status})`;
  
  // Toast notification ile kullanıcıya bildir
  Alpine.store('toast').add(message, status >= 500 ? 'error' : 'warning');
  
  if (status === 401 || status === 403) {
    setTimeout(() => window.location.href = '/login/', 2000);
  }
});
```

### Form Doğrulama Hataları

- Login: API yanıtı `data.status !== 'success'` ise `role="alert"` ile inline hata mesajı
- Setup: Her adımda zorunlu alan kontrolü, `role="alert"` ile alan altında hata mesajı
- 10 saniyelik timeout: `AbortController` ile API isteği iptal edilir

---

## Test Stratejisi

### Genel Yaklaşım

Bu özellik ağırlıklı olarak UI rendering, konfigürasyon doğrulama ve Alpine.js state yönetimini kapsamaktadır. Test stratejisi iki katmandan oluşur:

1. **Birim testleri**: Belirli örnekler, edge case'ler ve hata koşulları
2. **Özellik tabanlı testler (PBT)**: Evrensel özellikler, geniş input alanları

### Property-Based Testing Kütüphanesi

**Hypothesis (Python)** kullanılacaktır. Django test altyapısıyla doğal entegrasyon sağlar ve Alpine.js/DOM testleri için Playwright ile birlikte kullanılabilir.

```
pip install hypothesis playwright pytest-playwright
```

Her özellik testi minimum **100 iterasyon** çalıştırılacaktır.

### Test Etiket Formatı

```python
# Feature: corporate-ui-redesign, Property {N}: {property_text}
@given(...)
@settings(max_examples=100)
def test_property_N_description():
    ...
```

### Birim Test Kapsamı

**Build Pipeline Testleri:**
- `npm run build` sonrası `static/css/main.css` varlığı
- `package.json` script tanımları
- `tailwind.config.js` konfigürasyon yapısı
- CDN referanslarının `base.html`'den kaldırılması

**Theme Controller Testleri:**
- `localStorage` boşken `prefers-color-scheme` fallback
- Geçersiz `localStorage` değeri için `'dark'` varsayılanı
- 200ms içinde `dark` class değişikliği

**Login Sayfası Testleri:**
- Form submit sırasında düğme disabled + spinner görünümü
- Başarısız login sonrası `role="alert"` hata mesajı
- 10 saniye timeout sonrası düğme yeniden aktif

**Setup Wizard Testleri:**
- Zorunlu alan boşken "İleri" geçişinin engellenmesi
- PostgreSQL seçildiğinde ek alanların görünmesi
- E-posta format doğrulaması
- Şifre uzunluk doğrulaması

**Toast Testleri:**
- 5000ms sonra otomatik kaybolma
- Kapat düğmesiyle anında kaldırma
- 300ms animasyon süresi

**HTMX Entegrasyon Testleri:**
- Partial yükleme sonrası Alpine.js başlatma (500ms)
- `htmx:afterSwap` sonrası Flowbite yeniden başlatma

### Özellik Tabanlı Test Kapsamı

Yukarıda tanımlanan 14 özelliğin her biri için ayrı bir PBT yazılacaktır:

| Özellik | Test Yaklaşımı | Araç |
|---------|---------------|------|
| 1. Design Token Shade Bütünlüğü | `tailwind.config.js` parse, her grup için shade kontrolü | Hypothesis + Python |
| 2. WCAG Kontrast Uyumu | Renk çiftleri üret, kontrast hesapla | Hypothesis + wcag-contrast |
| 3. Tema Kalıcılığı | Başlangıç durumu üret, geçiş yap, state doğrula | Hypothesis + Playwright |
| 4. localStorage Önceliği | localStorage/prefers-color-scheme kombinasyonları | Hypothesis + Playwright |
| 5. Responsive Overflow Yok | 320-2560px arası viewport genişlikleri | Hypothesis + Playwright |
| 6. Mobil Dokunma Hedefi | Mobil viewport'ta element boyutları | Hypothesis + Playwright |
| 7. ARIA Etiket Bütünlüğü | Tüm etkileşimli elementler | Hypothesis + Playwright |
| 8. Sidebar Tekil Aktif State | Rastgele nav öğesi tıklamaları | Hypothesis + Playwright |
| 9. Toast Tür-Renk Tutarlılığı | 4 toast türü kombinasyonları | Hypothesis + Playwright |
| 10. Toast Maksimum Görünür Sayı | 1-10 arası toast sayıları | Hypothesis + Playwright |
| 11. HTMX Partial Tema Uyumu | Dark/light mode + partial yükleme | Hypothesis + Playwright |
| 12. Alpine.js Nitelik Korunumu | Rastgele hx-*/x-* nitelik kombinasyonları | Hypothesis + Playwright |
| 13. Setup Wizard Adım Durumu | 1-5 arası adım numaraları | Hypothesis + Playwright |
| 14. Mail Okunmamış Sayaç | Rastgele okunmamış e-posta seçimleri | Hypothesis + Playwright |

### Erişilebilirlik Test Stratejisi

WCAG 2.1 AA tam uyumu için otomatik testlerin yanı sıra manuel doğrulama gereklidir:

- **Otomatik**: axe-core ile Playwright entegrasyonu (kontrast, ARIA, label)
- **Manuel**: NVDA/VoiceOver ile ekran okuyucu testi
- **Manuel**: Yalnızca klavye navigasyonu testi
- **Manuel**: Windows High Contrast Mode testi

> **Not:** Tam WCAG uyumu doğrulaması, yardımcı teknolojilerle manuel test ve uzman erişilebilirlik incelemesi gerektirir. Otomatik testler tüm WCAG kriterlerini kapsamaz.

### Performans Test Kriterleri

| Metrik | Hedef |
|--------|-------|
| Üretim CSS boyutu | Geliştirme CSS'inden ≥%50 küçük |
| `npm run build` süresi | ≤60 saniye |
| Tema geçiş süresi | ≤200ms |
| Alpine.js başlatma (HTMX sonrası) | ≤500ms |
| Toast animasyon süresi | ≤300ms |
