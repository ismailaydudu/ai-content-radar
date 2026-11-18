"use client";


import { useEffect, useRef, useState } from "react";

type Health = {
  status: string;
  geminiConfigured: boolean;
  tmdbConfigured: boolean;
  sanityConfigured: boolean;
};
type Movie = {
  tmdbId: number;
  title: string;
  overview: string;
  targetAudience: string;
  threeWordSummary: string;
  radarScore: number;
  model: string;
  analyzedAt: string;
};
type MovieResponse = { movies: Movie[]; count: number; cached?: boolean };

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`/api/backend${path}`, { cache: "no-store", ...options });
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    throw new Error(typeof data?.error === "string" ? data.error : "Backend yanıt vermedi. Backend terminalinin açık olduğunu kontrol edin.");
  }
  if (!data) throw new Error("Backend geçerli bir yanıt döndürmedi.");
  return data as T;
}

function analysisDate(value: string) {
  const date = new Date(value);
  if (!value || Number.isNaN(date.getTime())) return "Kayıtlı analiz";
  return new Intl.DateTimeFormat("tr-TR", { dateStyle: "medium", timeStyle: "short", timeZone: "Europe/Istanbul" }).format(date);
}

export default function Home() {
  const [health, setHealth] = useState<Health | null>(null);
  const [movies, setMovies] = useState<Movie[]>([]);
  const [loading, setLoading] = useState(true);
  const [analyzing, setAnalyzing] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const analysisInProgress = useRef(false);

  useEffect(() => {
    const controller = new AbortController();
    async function load() {
      try {
        const [service, result] = await Promise.all([
          request<Health>("/health", { signal: controller.signal }),
          request<MovieResponse>("/api/movies", { signal: controller.signal }),
        ]);
        setHealth(service);
        setMovies(result.movies);
      } catch (cause) {
        if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : "Backend bağlantısı kurulamadı.");
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    }
    void load();
    return () => controller.abort();
  }, []);

  async function analyze() {
    if (analysisInProgress.current) return;
    analysisInProgress.current = true;
    setAnalyzing(true);
    setError("");
    setMessage("");
    try {
      const result = await request<MovieResponse>("/api/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      });
      if (result.count === 0 || result.movies.length === 0) {
        setMessage("Yeni film bulunamadı. Mevcut sonuçlar korunuyor.");
        return;
      }
      setMovies((current) => {
        const updated = new Map(result.movies.map((movie) => [movie.tmdbId, movie]));
        current.forEach((movie) => {
          if (!updated.has(movie.tmdbId)) updated.set(movie.tmdbId, movie);
        });
        return Array.from(updated.values());
      });
      setMessage(result.cached ? "Farklı film eklendi. Hazır analiz kullanıldı; Gemini isteği gönderilmedi." : "Yeni film analizi tamamlandı ve sonuç yerelde kaydedildi.");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Analiz tamamlanamadı.");
    } finally {
      analysisInProgress.current = false;
      setAnalyzing(false);
    }
  }

  const online = health?.status === "ok";
  

  return (
    <main className="min-h-screen bg-[#0b0f1a] text-slate-100">
      <div className="mx-auto max-w-6xl px-5 py-8 sm:px-8 sm:py-12">
        <header className="flex flex-wrap items-center justify-between gap-5 border-b border-white/10 pb-6">
          <div className="flex items-center gap-3">
            <span aria-hidden="true" className="flex h-11 w-11 items-center justify-center rounded-2xl bg-cyan-300/10 text-xl font-bold text-cyan-300 ring-1 ring-cyan-300/25">R</span>
            <div>
              <p className="text-lg font-semibold tracking-tight">AI Content Radar</p>
              <p className="text-xs text-slate-400">Film keşfi ve yapay zekâ analizi</p>
            </div>
          </div>
        </header>

        <section className="py-10 sm:py-14">
          <p className="mb-4 text-xs font-semibold tracking-[0.2em] text-cyan-300">İÇERİK RADARIN</p>
          <h1 className="max-w-3xl text-4xl font-semibold leading-tight tracking-tight sm:text-5xl">Bir sonraki filminin<br className="hidden sm:block" /> potansiyelini keşfet.</h1>
          <p className="mt-5 max-w-2xl text-base leading-7 text-slate-400">Popüler filmleri incele, hedef kitlelerini öğren ve Gemini tarafından üretilen radar skorlarını karşılaştır.</p>
        </section>

       

        <section className="mt-8 flex flex-col gap-5 rounded-2xl border border-cyan-300/15 bg-cyan-300/[0.04] p-5 sm:flex-row sm:items-center sm:justify-between sm:p-6">
          <div>
            <h2 className="text-lg font-semibold">Film analizi</h2>
            <p className="mt-2 max-w-xl text-sm leading-6 text-slate-400">Her tıklamada henüz analiz edilmemiş farklı bir film seçilir. Kayıt varsa kullanılır; yoksa en fazla tek Gemini isteği gönderilir. Sayfayı açmak analiz başlatmaz.</p>
            <p className="mt-2 text-xs text-slate-500">Sonuçlar yerelde saklanır. Sanity içerikleri değiştirilmez.</p>
          </div>
          <button type="button" onClick={() => void analyze()} disabled={loading || analyzing || !online} className="min-w-48 shrink-0 rounded-xl bg-cyan-300 px-5 py-3.5 text-sm font-semibold text-slate-950 transition hover:bg-cyan-200 disabled:cursor-not-allowed disabled:opacity-45">{analyzing ? "Analiz hazırlanıyor…" : "Yeni bir film analiz et"}</button>
        </section>

        <div aria-live="polite" className="mt-4">
          {analyzing && <p className="text-sm text-slate-400">Film bilgileri ve analiz hazırlanıyor… İşlem iki dakika sürebilir.</p>}
          {message && <p className="rounded-xl border border-emerald-400/20 bg-emerald-400/5 p-4 text-sm text-emerald-200">{message}</p>}
          {error && <p role="alert" className="rounded-xl border border-amber-400/20 bg-amber-400/5 p-4 text-sm leading-6 text-amber-200">{error}</p>}
        </div>

        <section className="mt-10" aria-labelledby="movies-heading">
          <div className="mb-5 flex items-center justify-between gap-3">
            <h2 id="movies-heading" className="text-xl font-semibold">Radar sonuçları</h2>
            <span className="rounded-full bg-white/5 px-3 py-1 text-xs text-slate-400">{movies.length} film</span>
          </div>
          {loading ? <p className="rounded-2xl border border-white/10 p-8 text-sm text-slate-400">Kayıtlı analizler yükleniyor…</p> : movies.length === 0 ? (
            <div className="rounded-2xl border border-dashed border-white/15 px-6 py-12 text-center">
              <h3 className="font-medium text-slate-200">Henüz kayıtlı analiz yok</h3>
              <p className="mt-3 text-sm leading-6 text-slate-400">İlk sonucu görmek için “Yeni bir film analiz et” düğmesini kullan.</p>
            </div>
          ) : (
            <div className="grid gap-5 md:grid-cols-2">
              {movies.map((movie) => (
                <article key={movie.tmdbId} className="rounded-2xl border border-white/10 bg-white/[0.025] p-6">
                  <div className="flex items-start justify-between gap-5">
                    <div>
                      <p className="text-xs font-medium uppercase tracking-wide text-cyan-300">{movie.threeWordSummary}</p>
                      <h3 className="mt-3 text-2xl font-semibold leading-tight">{movie.title}</h3>
                    </div>
                    <div className="shrink-0 rounded-2xl border border-cyan-300/20 bg-cyan-300/5 px-4 py-3 text-center" aria-label={`Radar skoru ${movie.radarScore}/10`}>
                      <p className="text-3xl font-semibold text-cyan-200">{movie.radarScore}<span className="text-sm text-slate-500">/10</span></p>
                      <p className="mt-1 text-[10px] font-semibold uppercase tracking-wider text-slate-400">Radar skoru</p>
                    </div>
                  </div>
                  <p className="mt-5 text-sm leading-7 text-slate-400">{movie.overview || "Film özeti bulunmuyor."}</p>
                  <div className="mt-5 border-t border-white/10 pt-4">
                    <p className="text-xs font-medium text-slate-500">HEDEF KİTLE</p>
                    <p className="mt-2 text-sm leading-6 text-slate-200">{movie.targetAudience}</p>
                  </div>
                  <footer className="mt-5 flex flex-wrap justify-between gap-2 text-xs text-slate-500">
                    <span>{movie.model}</span>
                    <span>{analysisDate(movie.analyzedAt)}</span>
                  </footer>
                </article>
              ))}
            </div>
          )}
        </section>
        <footer className="mt-12 border-t border-white/10 pt-5 text-xs leading-6 text-slate-500">Radar skorları yapay zekâ değerlendirmesidir. Servis ayarlarının tanımlı olması kota veya canlı API erişimi garantisi vermez.</footer>
      </div>
    </main>
  );
}
