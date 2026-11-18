# API motorunu kontrol etme

## Uygulamayı backend ve frontend ile çalıştırma

Birinci terminalde proje kökünden sürekli backend servisini başlatın:

```powershell
.\veri_motoru\env\Scripts\python.exe -u .\veri_motoru\server.py
```

İkinci terminalde:

```powershell
cd frontend
npm run dev
```

`http://localhost:3000` film analiz ekranıdır; `http://localhost:3000/studio`
Sanity Studio'dur. Backend `http://127.0.0.1:8000/health` adresinde çalışır.
Terminalleri açık bırakın; her servisi kendi terminalinde `Ctrl+C` ile durdurun.
Port doluysa aynı servisin başka terminalde çalışıp çalışmadığını kontrol edin.

Sayfa açılışında yalnızca yerel backend durumu ve kaydedilmiş film sonuçları okunur.
Ekrandaki **Yeni bir film analiz et** düğmesi daha önce analiz edilmiş film kimliklerini
atlar ve sıradaki farklı filmi seçer. Gerekirse popüler film listesinin en fazla beş
sayfası taranır. Gemini üretimi seçilen film/model için önbellek bulunmadığında
gerçekleşir. Her işlem bir filmle sınırlıdır; otomatik
tekrar yoktur. Aynı anda ikinci analiz isteği reddedilir. Bu servis Sanity'ye yazmaz.

Betikte aynı seçim için `--next` kullanılabilir. `--next` olmadan önceki ilk-film
seçimi ve analiz önbelleği davranışı korunur. Sayfa yenilemek yalnızca mevcut
sonuçları okur; yeni film analizi başlatmaz.

Backend ek bağımlılık gerektirmeden Python standart kütüphanesinin yerel HTTP
sunucusuyla çalışır. Frontend API isteklerini Next proxy üzerinden iletir; anahtarlar
tarayıcıya gönderilmez. Yerel geliştirme için `127.0.0.1` üzerinde dinler.

## Betik ve bağlantı kontrolleri

Proje kökünde PowerShell komutları:

```powershell
.\veri_motoru\env\Scripts\python.exe -m pip install -r .\veri_motoru\gereksinimler.txt
.\veri_motoru\env\Scripts\python.exe -m unittest discover -s .\veri_motoru -p "test_*.py" -v
.\veri_motoru\env\Scripts\python.exe .\veri_motoru\tmdb_cek.py --check
.\veri_motoru\env\Scripts\python.exe .\veri_motoru\ai_analiz.py
.\veri_motoru\env\Scripts\python.exe .\veri_motoru\tmdb_cek.py --dry-run --limit 1
```

Sanal ortam yoksa önce `py -m venv veri_motoru/env` çalıştırın.
Testler tamamen çevrimdışıdır; anahtar gerektirmez ve hiçbir API'ye bağlanmaz.
`--check`, Gemini model bilgisini ve Sanity belge sayısını salt okunur olarak sorgular.
Üretim kotasını veya Sanity yazma yetkisini doğrulamaz. Son iki komut Gemini üretim
isteği gönderir; kuru deneme ayrıca TMDB'den film okur. Hiçbiri Sanity verisini değiştirmez.

503/504 veren model yerine tek çalıştırmada Flash-Lite kullanmak için:

```powershell
.\veri_motoru\env\Scripts\python.exe .\veri_motoru\tmdb_cek.py --dry-run --limit 1 --model gemini-3.5-flash-lite
```

Başarılı analiz `veri_motoru/.cache/analysis` altında kaydedilir. Aynı TMDB filmi,
özet, model ve analiz sürümü için kayıt varsa yeni Gemini üretim isteği gönderilmez.
Başarısız yanıtlar kaydedilmez. Bu klasör yalnızca analiz sonucunu içerir;
API anahtarları veya `.env` içeriği kaydedilmez. 503 uzak servisin geçici
kullanılamadığını gösterir; model değiştirmek servis erişimini garanti etmez.

Python ayarları shell ortamından, sonra `veri_motoru/.env`, sonra proje kökündeki
`.env` dosyasından yüklenir. Mevcut değerler ezilmez. Gerekli değişken adları:

- `GEMINI_API_KEY`: Gemini erişimi.
- `GEMINI_MODEL`: isteğe bağlı; varsayılan `gemini-3.5-flash-lite`.
  `--model gemini-3.5-flash-lite` bu çalıştırmada ortam ayarının önüne geçer.
- `TMDB_API_KEY`: yalnızca film çekme akışı için.
- `SANITY_PROJECT_ID`, `SANITY_API_TOKEN`: Sanity kontrolü/yazımı için.
- `SANITY_DATASET`: varsayılan `production`; boş değer geçersizdir.
- `SANITY_API_VERSION`: varsayılan `2023-01-01`; `YYYY-MM-DD` biçiminde.

Frontend, kendi `frontend/.env.local` dosyasındaki `NEXT_PUBLIC_SANITY_PROJECT_ID`
ve `NEXT_PUBLIC_SANITY_DATASET` değişkenlerini kullanır. Python tarafındaki proje ve
dataset ile aynı hedefi göstermelidir. `NEXT_PUBLIC_SANITY_API_VERSION` isteğe bağlıdır.
API anahtarlarını/tokenleri `NEXT_PUBLIC_` değişkenlerine koymayın.

```powershell
cd frontend
npm run lint
npx tsc --noEmit
npm run dev
```

`http://localhost:3000/studio` adresinde Studio'yu açın. Belge kaydetmeden proje ve
dataset erişimini kontrol edin. Tarayıcıda CORS hatası varsa Sanity yönetim panelindeki
izinli origin ayarını (`http://localhost:3000`) kontrol edin. CLI veya TypeScript
kontrolünün geçmesi, uzak projenin yetkilerinin doğru olduğunu göstermez.

## Düzeltmeler ve hata ayrımı

- Eski `google.generativeai` kodu kaldırıldı; iki betik de `google-genai` kullanır.
  Bağımlılık dosyası dolduruldu; SDK ve model seçimi ortaktır.
- İçe aktarma sırasında API çağrısı yapılmaz. `tmdb_cek.py` varsayılan olarak kuru
  denemedir. Mevcut yayınlama yolu yalnızca açıkça `--write` verilirse çalışır.
  Bu bayrak veri oluşturur; inceleme ve kontrol komutlarında kullanmayın.
- Türkçe film adından `_id` üretilmez; Sanity kimliği üretir. Kaynak kimliği `tmdbId`
  alanında saklanır. Mevcut belgeler taşınmaz/güncellenmez. İleride yazım açılırsa
  aynı TMDB kimliği veya eski belgelerde aynı başlık varsa kayıt atlanır. Eşzamanlı
  iki yazıcı için bu sorgu atomik bir benzersizlik garantisi değildir.
- Boş metin, yanlış üç kelime veya 1–10 dışında/tamsayı olmayan skor reddedilir;
  yanlış değerler sessizce dönüştürülmez. Studio skor doğrulaması eklendi.
- Gemini yanıt zaman aşımı 120 saniyedir. Hem uygulama hem SDK otomatik tekrarları
  kapalıdır; her film için tek üretim isteği gönderilir. Varsayılan film sayısı 1'dir.
  Hatalar tekrar edilmeden anlaşılır mesaj verir; süreç hata durumunda sıfır dışında çıkar.
- Ham istisnalar, HTTP yanıt gövdeleri ve anahtarlı URL'ler ekrana yazılmaz.

401: kimlik doğrulama; 403: izin/anahtar kısıtları; 404: model/proje/dataset erişimi;
429: kota/hız sınırı. Bunlar olası nedenlerdir; canlı yanıt olmadan hangi hesabın
hangi hatayı verdiği kesinleştirilemez. Sanity tokeni doğru projeye ait olmalıdır;
salt okunur kontrolün geçmesi Editor/yazma yetkisi olduğu anlamına gelmez.
