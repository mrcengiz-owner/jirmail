# Gereksinimler Belgesi

## Giriş

Bu belge, jir-mail projesinin kurumsal bir UI tasarımına geçişini kapsamaktadır. Mevcut Django 5.2 + HTMX + Alpine.js stack'i korunarak Tailwind CSS CDN bağımlılığı kaldırılacak, yerine Vite tabanlı bir build pipeline kurulacaktır. Flowbite veya DaisyUI gibi kurumsal bir component library entegre edilecek, design token sistemi oluşturulacak ve tüm sayfalar (Login, Setup, Master Panel, Mail Panel) kurumsal görünüm standartlarına yükseltilecektir. Sonuç; WCAG 2.1 AA uyumlu, light/dark mode destekli, responsive ve erişilebilir bir yönetim arayüzü olacaktır.

---

## Sözlük

- **UI_System**: Jir-Mail'in tüm frontend katmanını yöneten sistem bütünü.
- **Build_Pipeline**: Tailwind CSS ve diğer frontend varlıklarını derleyen Vite + PostCSS tabanlı araç zinciri.
- **Design_Token**: Renk, tipografi, spacing ve gölge gibi tasarım kararlarını merkezi olarak tanımlayan değişken seti.
- **Component_Library**: Flowbite veya DaisyUI tabanlı, yeniden kullanılabilir UI bileşenleri koleksiyonu.
- **Theme_Controller**: Light/dark mode geçişini yöneten Alpine.js tabanlı bileşen.
- **Master_Panel**: Yönetici rolüne sahip kullanıcıların eriştiği Dashboard, Accounts, Domains, Backup, Logs ve Containers sekmelerini içeren panel.
- **Mail_Panel**: Son kullanıcıların eriştiği, Gmail benzeri 3 sütunlu e-posta arayüzü.
- **Setup_Wizard**: İlk kurulum adımlarını yönlendiren çok adımlı form sihirbazı.
- **Login_Page**: Kimlik doğrulama formunu barındıran giriş sayfası.
- **Partial_Template**: HTMX ile dinamik olarak yüklenen Django HTML parçaları.
- **Toast_Notification**: Kullanıcıya anlık geri bildirim sağlayan geçici bildirim bileşeni.
- **Sidebar**: Master Panel'in sol tarafında yer alan navigasyon bileşeni.
- **WCAG_2_1_AA**: Web Content Accessibility Guidelines 2.1, AA uyumluluk seviyesi.

---

## Gereksinimler

### Gereksinim 1: Tailwind CSS Build Pipeline Kurulumu

**Kullanıcı Hikayesi:** Bir geliştirici olarak, Tailwind CSS'i CDN yerine yerel build pipeline üzerinden derlemek istiyorum; böylece üretim ortamında kullanılmayan CSS sınıfları tree-shaking ile temizlensin ve bundle boyutu küçülsün.

#### Kabul Kriterleri

1. THE Build_Pipeline SHALL Tailwind CSS v3'ü PostCSS aracılığıyla derleyerek `static/css/main.css` çıktısını üretmek. (Tailwind v4 değil v3 kullanılacak; mevcut `tailwind.config` inline yapısı `tailwind.config.js` dosyasına taşınacak.)
2. THE Build_Pipeline SHALL `package.json` içinde `build` (tek seferlik derleme) ve `watch` (dosya değişikliklerini izleyerek otomatik yeniden derleme) script'lerini tanımlamak.
3. WHEN `npm run build` komutu çalıştırıldığında, THE Build_Pipeline SHALL `templates/**/*.html` ve `static/js/**/*.js` dosyalarını tarayarak kullanılan Tailwind sınıflarını tespit etmek ve kullanılmayanları çıktıdan çıkarmak (PurgeCSS/content tarama).
4. THE Build_Pipeline SHALL Django'nun `collectstatic` akışıyla uyumlu olacak şekilde çıktı dosyasını `static/css/main.css` yoluna yazmak.
5. IF `npm run build` komutu sırasında bir hata oluşursa, THEN THE Build_Pipeline SHALL hata mesajını standart çıktıya (stderr) yazmak ve sıfırdan farklı bir çıkış kodu (non-zero exit code) döndürmek.
6. WHEN Build_Pipeline kurulumu tamamlandığında, THE UI_System SHALL `base.html` içindeki `<script src="https://cdn.tailwindcss.com">` etiketini kaldırmak ve yerine `<link rel="stylesheet" href="{% static 'css/main.css' %}">` eklemek.
7. THE Build_Pipeline SHALL `base.html` içindeki inline `tailwind.config = { ... }` JavaScript bloğunu `tailwind.config.js` dosyasına taşımak; mevcut `slate`, `emerald` renk genişletmeleri ve `pulse-slow` animasyonu korunmak.

---

### Gereksinim 2: Component Library Entegrasyonu

**Kullanıcı Hikayesi:** Bir geliştirici olarak, kurumsal görünümlü, erişilebilir ve tutarlı UI bileşenleri kullanmak istiyorum; böylece her bileşeni sıfırdan yazmak yerine kanıtlanmış bir kütüphaneden yararlanayım.

#### Kabul Kriterleri

1. THE UI_System SHALL Flowbite veya DaisyUI kütüphanelerinden birini `tailwind.config.js` dosyasının `plugins` dizisine ekleyerek Tailwind CSS eklentisi olarak entegre etmek; entegrasyon, `npm run build` sonrasında derlenen CSS çıktısında kütüphane sınıflarının mevcut olmasıyla doğrulanmak.
2. WHEN bir sayfa render edildiğinde, THE Component_Library SHALL button, input, modal, dropdown, badge, card, table ve alert bileşenlerini görünür ve işlevsel biçimde sunmak.
3. WHEN bir bileşen render edildiğinde, THE Component_Library SHALL hem light hem de dark mode'da arka plan, metin ve kenarlık renklerini Design_Token değerleriyle uyumlu biçimde göstermek; unstyled (stilsiz) fallback görünümü render edilmemek.
4. THE Component_Library SHALL mevcut HTMX `hx-*` ve Alpine.js `x-*` nitelikleriyle aynı DOM elementinde kullanıldığında bu nitelikleri DOM'dan kaldırmamak ve bileşen işlevselliğini bozmamak.
5. WHERE Flowbite seçilirse, THE UI_System SHALL Flowbite JavaScript başlatmasını Alpine.js `init` yaşam döngüsü tamamlandıktan sonra çalıştırmak; aynı DOM elementi üzerinde Alpine.js ve Flowbite olay dinleyicileri eş zamanlı aktif olmak.
6. WHERE DaisyUI seçilirse, THE UI_System SHALL DaisyUI CSS değişkenlerinin tamamını (`--color-primary`, `--color-secondary` vb.) Design_Token sistemiyle eşleştirmek; eşleştirilmemiş DaisyUI değişken sayısı sıfır olmak.

---

### Gereksinim 3: Design Token Sistemi

**Kullanıcı Hikayesi:** Bir tasarımcı veya geliştirici olarak, renk, tipografi ve spacing değerlerini merkezi bir yerden yönetmek istiyorum; böylece tutarlı bir görsel dil oluşturulsun ve gelecekteki tema değişiklikleri kolaylaşsın.

#### Kabul Kriterleri

1. THE Design_Token SHALL `colors`, `fontFamily`, `fontSize`, `spacing`, `borderRadius` ve `boxShadow` kategorilerinde `tailwind.config.js` dosyasının `theme.extend` bölümünde tanımlanmak.
2. THE Design_Token SHALL `primary`, `secondary`, `success`, `warning`, `danger` ve `neutral` semantik renk gruplarını içermek; her grup en az `50`, `100`, `200`, `300`, `400`, `500`, `600`, `700`, `800`, `900` shade değerlerine sahip olmak.
3. IF dark mode aktifse (`<html class="dark">`), THEN THE UI_System SHALL tüm bileşenlerde `dark:` prefix'li Tailwind sınıflarını kullanarak dark mode Design_Token renk değerlerini uygulamak.
4. THE Design_Token SHALL tipografi için en az iki font ailesi tanımlamak: başlıklar ve gövde metni için `sans-serif` (`Inter` veya eşdeğeri) ve kod blokları için `monospace` (`JetBrains Mono` veya eşdeğeri).
5. WHEN bir Design_Token değeri `tailwind.config.js` içinde değiştirildiğinde ve `npm run build` komutu 60 saniye içinde tamamlandığında, THE Build_Pipeline SHALL güncellenmiş değeri derlenen CSS çıktısına yansıtmak.
6. THE Design_Token SHALL mevcut `slate-850`, `slate-900`, `slate-950`, `emerald-400`, `emerald-500`, `emerald-600` renk değerlerini korumak ve bunları `primary` semantik renk grubuyla eşleştirmek; ek olarak `secondary`, `success`, `warning`, `danger` grupları için WCAG 2.1 AA kontrast oranını (4.5:1) karşılayan renk değerleri tanımlamak.

---

### Gereksinim 4: Light/Dark Mode Desteği

**Kullanıcı Hikayesi:** Bir kullanıcı olarak, arayüzü light veya dark modda kullanmak istiyorum; böylece farklı ortam koşullarında göz yorgunluğunu azaltayım.

#### Kabul Kriterleri

1. WHEN kullanıcı tema geçiş düğmesine tıkladığında, THE Theme_Controller SHALL seçilen temayı (`"light"` veya `"dark"` string değeri olarak) `localStorage` anahtarı `theme` altına kaydetmek.
2. WHEN sayfa yüklendiğinde, THE Theme_Controller SHALL `localStorage.getItem("theme")` değerini okumak ve bu değere göre `<html>` elementine `dark` sınıfını eklemek veya kaldırmak.
3. IF `localStorage`'da `theme` anahtarı mevcut değilse, THEN THE Theme_Controller SHALL `window.matchMedia("(prefers-color-scheme: dark)").matches` değerini varsayılan tema olarak kullanmak.
4. IF `localStorage`'da `theme` anahtarı mevcutsa, THEN THE Theme_Controller SHALL sistem `prefers-color-scheme` tercihini yok sayarak `localStorage` değerini öncelikli olarak uygulamak.
5. WHILE dark mode aktifken (`<html class="dark">`), THE UI_System SHALL tüm sayfalarda arka plan, metin, kenarlık ve bileşen renklerini dark mode Design_Token değerleriyle render etmek.
6. WHILE light mode aktifken (`<html>` elementinde `dark` sınıfı yokken), THE UI_System SHALL tüm sayfalarda arka plan, metin, kenarlık ve bileşen renklerini light mode Design_Token değerleriyle render etmek.
7. WHEN kullanıcı tema geçiş düğmesine tıkladığında, THE Theme_Controller SHALL `<html>` elementindeki `dark` sınıfı değişikliğini 200ms veya daha kısa sürede tamamlamak; CSS `transition` süresi bu sınırı aşmamak.
8. THE Theme_Controller SHALL sidebar veya header içinde görünür bir tema geçiş düğmesi (ikon veya toggle) render etmek; düğme her iki modda da WCAG 2.1 AA kontrast oranını karşılamak.

---

### Gereksinim 5: Responsive Tasarım

**Kullanıcı Hikayesi:** Bir yönetici olarak, paneli masaüstü, tablet ve mobil cihazlardan kullanmak istiyorum; böylece farklı ekran boyutlarında verimli çalışabileyim.

#### Kabul Kriterleri

1. THE UI_System SHALL 320px ile 2560px arasındaki ekran genişliklerinde tüm navigasyon öğelerine, form alanlarına ve içerik alanlarına erişilebilir ve kullanılabilir biçimde render etmek; hiçbir içerik kesilmemek veya üst üste binmemek.
2. WHEN ekran genişliği 768px'in altına düştüğünde, THE Sidebar SHALL `display: none` veya `transform: translateX(-100%)` ile gizlenmek; bir hamburger menü düğmesi (`☰`) görünür olmak ve bu düğmeye tıklandığında Sidebar overlay olarak açılmak.
3. WHEN ekran genişliği 768px'in altına düştüğünde, THE Master_Panel SHALL çok sütunlu grid düzenini tek sütunlu (`grid-cols-1`) düzene geçirmek; tüm kartlar ve tablolar tam genişlikte render edilmek.
4. WHEN ekran genişliği 768px'in altına düştüğünde, THE Mail_Panel SHALL 3 sütunlu düzenden tek sütunlu düzene geçmek; varsayılan olarak klasör listesi sütunu görünmek, bir e-posta seçildiğinde e-posta listesi sütununa, e-posta listesinden bir öğe seçildiğinde içerik sütununa geçmek; her sütunda geri navigasyon düğmesi (`←`) bulunmak.
5. WHEN ekran genişliği 768px'in altında olduğunda, THE UI_System SHALL tüm tıklanabilir öğelerin (button, link, nav item) minimum 44x44px boyutunda dokunma hedefi alanına sahip olmasını sağlamak.
6. THE UI_System SHALL tüm sayfalarda `overflow-x: hidden` veya eşdeğer Tailwind sınıflarıyla yatay kaydırmayı önlemek; 320px genişliğinde hiçbir içerik viewport dışına taşmamak.

---

### Gereksinim 6: Erişilebilirlik (WCAG 2.1 AA)

**Kullanıcı Hikayesi:** Bir kullanıcı olarak, ekran okuyucu veya klavye ile arayüzü kullanabilmek istiyorum; böylece yardımcı teknolojilere bağımlı kullanıcılar da sisteme erişebilsin.

#### Kabul Kriterleri

1. THE UI_System SHALL tüm etkileşimli bileşenlerde (button, input, link, select) görünür metin etiketi yoksa `aria-label` niteliği, birden fazla ilgili element varsa `aria-labelledby` veya `aria-describedby` niteliği sağlamak; bu niteliklerden en az biri her etkileşimli elementte mevcut olmak.
2. THE UI_System SHALL klavye navigasyonunu desteklemek; Tab tuşuyla odak sırası DOM kaynak sırasını izlemek, odak göstergesi en az 2px kalınlığında ve arka planla en az 3:1 kontrast oranına sahip görünür bir outline ile render edilmek.
3. THE UI_System SHALL metin ve arka plan renkleri arasında WCAG 2.1 AA standardının gerektirdiği en az 4.5:1 kontrast oranını sağlamak (normal metin için).
4. THE UI_System SHALL büyük metin (18pt/24px veya 14pt/18.67px bold) için en az 3:1 kontrast oranını sağlamak.
5. THE UI_System SHALL durum bilgisini (hata, uyarı, başarı) renk ile birlikte ikon ve/veya metin etiketi kullanarak iletmek; renk kaldırıldığında bilgi kaybı yaşanmamak.
6. WHEN bir modal veya dropdown açıldığında, THE UI_System SHALL odağı modal/dropdown içindeki ilk odaklanabilir elemana taşımak; Escape tuşuna basıldığında veya modal kapatıldığında odağı tetikleyici elemana geri döndürmek; modal açıkken Tab tuşu odağı modal dışına çıkarmamak (focus trap).
7. THE UI_System SHALL tüm form alanlarına programatik olarak ilişkilendirilmiş görünür `<label>` veya `aria-label` sağlamak; placeholder metni tek başına etiket olarak kullanmamak.
8. WHEN `prefers-reduced-motion: reduce` medya sorgusu aktifse, THE UI_System SHALL tüm CSS `transition` ve `animation` sürelerini 0ms veya 1ms'ye indirmek ya da animasyonları tamamen devre dışı bırakmak.

---

### Gereksinim 7: Login Sayfası Yeniden Tasarımı

**Kullanıcı Hikayesi:** Bir kullanıcı olarak, kurumsal ve güven verici bir giriş ekranıyla karşılaşmak istiyorum; böylece ürünün profesyonelliğini ilk anda hissedeyim.

#### Kabul Kriterleri

1. THE Login_Page SHALL marka logosu (SVG veya `<img>`), "Jîr-Mail" uygulama adı ve kısa açıklama metnini içeren bir başlık bölümü render etmek.
2. THE Login_Page SHALL e-posta alanı (`type="email"`, `autocomplete="username"`), şifre alanı (`type="password"`, `autocomplete="current-password"`, varsayılan olarak gizli), şifre görünürlük geçiş düğmesi (göz ikonu) ve giriş düğmesini içeren bir form render etmek.
3. WHEN giriş formu gönderildiğinde, THE Login_Page SHALL giriş düğmesini `disabled` duruma getirmek ve spinner ikonu göstermek; bu durum API yanıtı alınana kadar veya en fazla 10 saniye sürmek.
4. IF 10 saniye içinde API yanıtı alınamazsa, THEN THE Login_Page SHALL giriş düğmesini yeniden aktif etmek ve form içinde "Bağlantı zaman aşımına uğradı, lütfen tekrar deneyin." mesajını göstermek.
5. IF kimlik doğrulama başarısız olursa, THEN THE Login_Page SHALL hata mesajını form elementinin içinde, giriş düğmesinin üzerinde inline olarak göstermek; hata mesajı `role="alert"` niteliğine sahip olmak.
6. THE Login_Page SHALL light modda beyaz/açık gri arka plan üzerinde koyu metin, dark modda koyu arka plan üzerinde açık metin render etmek; her iki modda da metin/arka plan kontrast oranı 4.5:1'den az olmamak.
7. THE Login_Page SHALL 320px ile 1920px arasındaki ekran genişliklerinde form elemanlarının kesilmeden ve üst üste binmeden render edilmesini sağlamak.
8. IF ağ bağlantısı yoksa veya sunucu erişilemez durumdaysa, THEN THE Login_Page SHALL form içinde "Sunucuya bağlanılamıyor, ağ bağlantınızı kontrol edin." mesajını göstermek.

---

### Gereksinim 8: Setup Sihirbazı Yeniden Tasarımı

**Kullanıcı Hikayesi:** Bir sistem yöneticisi olarak, ilk kurulum adımlarını net ve yönlendirici bir arayüzde tamamlamak istiyorum; böylece kurulum sürecinde kaybolmayayım.

#### Kabul Kriterleri

1. THE Setup_Wizard SHALL mevcut adımı (vurgulu), tamamlanan adımları (onay ikonu) ve kalan adımları (pasif) gösteren bir stepper bileşeni render etmek; stepper her adım geçişinde güncellenmek.
2. THE Setup_Wizard SHALL her adımda "İleri" düğmesi sağlamak; ilk adım dışındaki tüm adımlarda "Geri" düğmesi de sağlamak.
3. WHEN bir adım tamamlandığında ve "İleri" düğmesine tıklandığında, THE Setup_Wizard SHALL stepper'da o adımı tamamlandı olarak işaretlemek ve bir sonraki adıma geçmek.
4. IF bir adımda zorunlu alan boş bırakılırsa, THEN THE Setup_Wizard SHALL "İleri" düğmesine tıklandığında ileri geçişi engellemek ve hata mesajını ilgili alanın hemen altında `role="alert"` niteliğiyle göstermek.
5. IF PostgreSQL veritabanı seçilirse, THEN THE Setup_Wizard SHALL host, port, veritabanı adı, kullanıcı adı ve şifre alanlarını zorunlu alan olarak göstermek ve bu alanlar boşken "İleri" geçişini engellemek.
6. THE Setup_Wizard SHALL admin e-posta alanında geçerli e-posta formatı (`RFC 5322`) doğrulaması yapmak; geçersiz formatta "Geçerli bir e-posta adresi girin." mesajını göstermek.
7. THE Setup_Wizard SHALL admin şifre alanında en az 8 karakter uzunluğu doğrulaması yapmak; kısa şifrede "Şifre en az 8 karakter olmalıdır." mesajını göstermek.
8. THE Setup_Wizard SHALL her adımın amacını açıklayan başlık (`<h2>`) ve yardım metni (`<p>`) render etmek.
9. THE Setup_Wizard SHALL light modda beyaz/açık gri arka plan, dark modda koyu arka plan render etmek; her iki modda da metin/arka plan kontrast oranı 4.5:1'den az olmamak.
10. IF kurulum tamamlama API çağrısı başarısız olursa, THEN THE Setup_Wizard SHALL hata mesajını son adımın form alanlarının altında göstermek ve kullanıcının tekrar denemesine izin vermek.

---

### Gereksinim 9: Master Panel Yeniden Tasarımı

**Kullanıcı Hikayesi:** Bir sistem yöneticisi olarak, tüm yönetim işlevlerine hızlı erişebileceğim, bilgi yoğunluğu yüksek ama okunabilir bir panel kullanmak istiyorum.

#### Kabul Kriterleri

1. WHEN bir navigasyon öğesine tıklandığında ve ilgili sekme yüklendiğinde, THE Sidebar SHALL aktif öğeyi `aria-current="page"` niteliğiyle işaretlemek ve Design_Token `primary` renk grubuyla arka plan ve metin rengini pasif öğelerden görsel olarak ayırt etmek.
2. THE Sidebar SHALL navigasyon öğelerini `Overview` (Dashboard), `Mail System` (Accounts, Domains) ve `Management` (Backup, Logs, Containers) bölüm başlıklarıyla gruplamak; başlıklar `<span>` veya `<p>` ile render edilmek.
3. THE Master_Panel SHALL Dashboard sekmesinde aktif hesap sayısı, toplam domain sayısı, disk kullanım yüzdesi ve Postfix/Dovecot servis durumu (çalışıyor/durdu) bilgilerini ayrı kartlarda render etmek; veriler `/api/management/system-specs` ve `/api/management/health` endpoint'lerinden alınmak.
4. THE Master_Panel SHALL Accounts sekmesinde e-posta, kullanıcı adı ve durum sütunlarında arama/filtreleme destekli, sayfa başına 20 kayıt gösteren sayfalama destekli bir tablo render etmek; arama sonucu sıfır kayıt olduğunda "Sonuç bulunamadı." mesajı göstermek.
5. THE Master_Panel SHALL Domains sekmesinde domain adı, aktiflik durumu ve DNS doğrulama durumu (`pending`/`verified`/`failed`) sütunlarını içeren bir tablo render etmek; doğrulama durumu renk kodlu rozet (badge) ile göstermek.
6. THE Master_Panel SHALL Backup sekmesinde yedek adı, türü, boyutu, durumu ve oluşturulma tarihini içeren yedek listesini ve "Yedek Al" düğmesini render etmek.
7. THE Master_Panel SHALL Logs sekmesinde sayfalanmış log listesini render etmek; her log satırı zaman damgası ve mesaj içermek; en yeni loglar en üstte görünmek.
8. THE Master_Panel SHALL Containers sekmesinde her Docker container için ad, durum (`running`/`stopped`/`exited`) ve yeniden başlatma düğmesini render etmek; durum renk kodlu rozet ile göstermek.
9. WHEN bir HTMX isteği devam ederken, THE Master_Panel SHALL içerik alanında dönen bir spinner (`animate-spin`) render etmek; istek tamamlandığında spinner kaybolmak.

---

### Gereksinim 10: Mail Panel Yeniden Tasarımı

**Kullanıcı Hikayesi:** Bir mail kullanıcısı olarak, Gmail benzeri akıcı bir arayüzde e-postalarımı yönetmek istiyorum; böylece alışkın olduğum deneyimi kurumsal bir görünümde yaşayayım.

#### Kabul Kriterleri

1. THE Mail_Panel SHALL klasör listesi (sol sütun, ~20% genişlik), e-posta listesi (orta sütun, ~35% genişlik) ve e-posta içeriği (sağ sütun, ~45% genişlik) olmak üzere 3 sütunlu bir düzen render etmek.
2. THE Mail_Panel SHALL okunmamış e-posta sayısını klasör listesinde her klasörün yanında rozet (badge) olarak göstermek; okunmamış sayı sıfır olduğunda rozeti gizlemek.
3. WHEN bir e-posta seçildiğinde, THE Mail_Panel SHALL e-posta içeriğini sağ sütunda render etmek ve seçilen e-postayı okundu olarak işaretlemek (okunmamış rozet sayısını azaltmak).
4. THE Mail_Panel SHALL e-posta listesinde her öğe için gönderici adı, konu, önizleme metni (ilk 100 karakter) ve tarih/saat bilgilerini göstermek.
5. THE Mail_Panel SHALL okunmamış e-postaları `font-semibold` veya `font-bold` ile, okunmuş e-postaları `font-normal` ile render etmek; her iki durumda da arka plan rengi farkı ek görsel ayrım sağlamak.
6. WHEN ekran genişliği 768px'in altına düştüğünde, THE Mail_Panel SHALL tek sütunlu düzene geçmek; varsayılan görünüm klasör listesi sütunu olmak, bir klasöre tıklandığında e-posta listesi sütununa geçmek, bir e-postaya tıklandığında içerik sütununa geçmek; her sütunda önceki sütuna dönen `←` geri düğmesi bulunmak.

---

### Gereksinim 11: Toast Bildirim Sistemi Yeniden Tasarımı

**Kullanıcı Hikayesi:** Bir kullanıcı olarak, gerçekleştirdiğim işlemlerin sonucunu anlık ve net bir şekilde görmek istiyorum; böylece işlemin başarılı mı yoksa başarısız mı olduğunu hemen anlayayım.

#### Kabul Kriterleri

1. THE Toast_Notification SHALL `success` (yeşil + onay ikonu), `error` (kırmızı + çarpı ikonu), `warning` (sarı + uyarı ikonu) ve `info` (mavi + bilgi ikonu) türlerini desteklemek; her tür için renk ve ikon eşlemesi sabit ve tutarlı olmak.
2. THE Toast_Notification SHALL ekranın sağ alt köşesinde `position: fixed; bottom: 1rem; right: 1rem; z-index: 9999` veya eşdeğer Tailwind sınıflarıyla render edilmek.
3. WHEN bir toast bildirimi gösterildiğinde, THE Toast_Notification SHALL 5000ms (5 saniye) sonra otomatik olarak kaybolmak; sayaç toast gösterildiği anda başlamak.
4. WHEN kullanıcı kapat düğmesine (`×`) tıkladığında, THE Toast_Notification SHALL otomatik kaybolma sayacını iptal etmek ve bildirimi hemen kaldırmak.
5. WHEN ikinci bir toast bildirimi gösterildiğinde, THE Toast_Notification SHALL mevcut bildirimin üzerine dikey olarak yığılmak; maksimum 5 bildirim aynı anda görünmek, 5'i aşan bildirimler kuyruğa alınmak.
6. THE Toast_Notification SHALL görünme animasyonunu (slide-in veya fade-in) 300ms veya daha kısa sürede, kaybolma animasyonunu (slide-out veya fade-out) 300ms veya daha kısa sürede tamamlamak.
7. THE Toast_Notification SHALL `role="status"` ve `aria-live="polite"` nitelikleriyle render edilmek; `error` türü için `aria-live="assertive"` kullanmak.

---

### Gereksinim 12: Partial Template Uyumluluğu

**Kullanıcı Hikayesi:** Bir geliştirici olarak, HTMX ile yüklenen partial template'lerin yeni tasarım sistemiyle uyumlu olmasını istiyorum; böylece dinamik içerik yüklemelerinde görsel tutarsızlık yaşanmasın.

#### Kabul Kriterleri

1. THE Partial_Template SHALL Design_Token sınıflarını ve Component_Library bileşenlerini kullanmak; hardcoded renk değerleri (`#1a2234`, `rgb(...)` vb.) veya inline `style=""` nitelikleri içermemek.
2. WHEN bir Partial_Template HTMX ile yüklendiğinde, THE UI_System SHALL yeni yüklenen içeriğin `<html>` elementindeki `dark` sınıfını miras alarak mevcut tema ile uyumlu render edilmesini sağlamak; tema geçişi gerektirmeden doğru renklerin uygulanmış olması beklenmek.
3. THE Partial_Template SHALL `<style>` etiketi veya `style=""` niteliği içermemek; tüm stiller Build_Pipeline tarafından derlenen `static/css/main.css` dosyasından gelmek.
4. WHEN `x-data` niteliği içeren bir Partial_Template HTMX ile yüklendiğinde, THE UI_System SHALL Alpine.js'in yeni yüklenen bileşenleri 500ms içinde başlatmasını sağlamak; `x-data` bileşenlerinin reaktif bağlamaları bu süre içinde aktif olmak.

---

### Gereksinim 13: Performans ve Üretim Hazırlığı

**Kullanıcı Hikayesi:** Bir DevOps mühendisi olarak, frontend varlıklarının üretim ortamında optimize edilmiş şekilde sunulmasını istiyorum; böylece sayfa yükleme süreleri kabul edilebilir sınırlar içinde kalsın.

#### Kabul Kriterleri

1. WHEN `npm run build` komutu `NODE_ENV=production` ortam değişkeniyle çalıştırıldığında, THE Build_Pipeline SHALL CSS çıktısını minify etmek; çıktı dosyası yorum satırları ve gereksiz boşluklar içermemek.
2. WHEN `npm run build` komutu `NODE_ENV=production` ortam değişkeniyle çalıştırıldığında, THE Build_Pipeline SHALL kullanılmayan CSS sınıflarını çıktıdan kaldırmak; üretim CSS çıktısı geliştirme çıktısından en az %50 daha küçük olmak.
3. THE UI_System SHALL `base.html` içinde CSS dosyasını `<link rel="stylesheet" href="...">` ile, JavaScript dosyalarını `defer` veya `async` niteliğiyle yüklemek; render-blocking kaynak bulunmamak.
4. WHEN `npm ci && npm run build` komut dizisi çalıştırıldığında, THE Build_Pipeline SHALL sıfır çıkış kodu (exit code 0) ile tamamlanmak; bu komut Dockerfile `RUN` adımı veya CI/CD pipeline adımı olarak kullanılabilmek.
5. IF `python manage.py collectstatic --noinput` komutu çalıştırıldığında, THEN THE UI_System SHALL Build_Pipeline tarafından üretilen en az bir CSS dosyası ve en az bir JavaScript dosyasını Django'nun `STATIC_ROOT` dizinine kopyalamak.
