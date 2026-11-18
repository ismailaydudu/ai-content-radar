"""Varsayilan calisma kuru denemedir. Sanity yazimi --write gerektirir."""
import argparse
import json
import sys

import requests

from analysis_cache import read_analysis_cache, write_analysis_cache
from movie_store import read_movie_documents, save_movie_document
from api_utils import (
    ApiError, check_gemini_model, check_status, create_gemini_client,
    gemini_analiz_et, gemini_model, get_json, load_settings, required_env, sanity_settings,
)


def movie_document(film, analysis):
    if type(film.get('id')) is not int or film['id'] <= 0:
        raise ApiError('TMDB film kimligi gecersiz.')
    return {
        '_type': 'movie', 'tmdbId': film['id'],
        'title': film['title'].strip(), 'overview': film['overview'].strip(),
        'targetAudience': analysis['hedef_kitle'],
        'threeWordSummary': analysis['uc_kelime'], 'radarScore': analysis['skor'],
    }


def publish_movie(settings, document):
    # Match legacy titles too: old documents did not have tmdbId.
    existing = get_json(
        f"{settings['base_url']}/data/query/{settings['dataset']}", 'Sanity',
        headers=settings['headers'], params={
            'query': 'count(*[_type == "movie" && (tmdbId == $tmdbId || (!defined(tmdbId) && title == $title))])',
            '$tmdbId': str(document['tmdbId']), '$title': json.dumps(document['title']),
        },
    )
    if type(existing.get('result')) is not int:
        raise ApiError('Sanity sorgu yaniti gecersiz.')
    if existing['result']:
        print('Film zaten mevcut; atlaniyor.')
        return
    # Sanity generates an ID; Turkish title characters are invalid in document IDs.
    try:
        response = requests.post(
            f"{settings['base_url']}/data/mutate/{settings['dataset']}",
            headers=settings['headers'], json={'mutations': [{'create': document}]}, timeout=20,
        )
    except requests.RequestException:
        raise ApiError('Sanity baglanti hatasi; yazim sonucu belirsiz. Otomatik tekrar yapilmadi.') from None
    check_status(response, 'Sanity')
    print('Sanity kaydi olusturuldu.')


def check_sanity(settings):
    data = get_json(
        f"{settings['base_url']}/data/query/{settings['dataset']}", 'Sanity',
        headers=settings['headers'], params={'query': 'count(*[_type == "movie"])'},
    )
    if type(data.get('result')) is not int:
        raise ApiError('Sanity sorgu yaniti gecersiz.')
    print('Sanity salt okunur sorgusu basarili. Yazma yetkisi kontrol edilmedi.')


def fetch_popular_page(page=1):
    return get_json('https://api.themoviedb.org/3/movie/popular', 'TMDB', params={
        'api_key': required_env('TMDB_API_KEY'), 'language': 'tr-TR', 'page': page,
    })


def valid_film(film):
    return (
        isinstance(film, dict)
        and type(film.get('id')) is int and film['id'] > 0
        and isinstance(film.get('title'), str) and bool(film['title'].strip())
        and isinstance(film.get('overview'), str) and bool(film['overview'].strip())
    )


def select_unanalyzed_films(limit=1):
    existing_ids = {document['tmdbId'] for document in read_movie_documents()}
    selected = []
    for page in range(1, 6):
        data = fetch_popular_page(page)
        films = data.get('results')
        if not isinstance(films, list):
            raise ApiError('TMDB film listesi gecersiz.')
        for film in films:
            if not valid_film(film) or film['id'] in existing_ids:
                continue
            selected.append(film)
            existing_ids.add(film['id'])
            if len(selected) >= limit:
                return selected
        total_pages = data.get('total_pages', 1)
        if not films or type(total_pages) is not int or page >= total_pages:
            break
    if not selected:
        raise ApiError('Taranan populer filmlerde yeni analiz edilecek film bulunamadi. Gemini istegi gonderilmedi.')
    return selected


def analyze_movies(limit=1, model=None, write=False, allow_generation=True, next_unanalyzed=False):
    if type(limit) is not int or limit < 1:
        raise ApiError('Film sayisi en az 1 olmali.')
    load_settings()
    model = model or gemini_model()
    settings = sanity_settings() if write else None
    if next_unanalyzed:
        films = select_unanalyzed_films(limit)
    else:
        films = fetch_popular_page().get('results')
        if not isinstance(films, list):
            raise ApiError('TMDB film listesi gecersiz.')
    print('Sanity yazimi acik.' if write else 'Sanity verileri degistirilmeyecek.')
    documents = []
    all_cached = True
    for film in films[:limit]:
        if not isinstance(film, dict) or not isinstance(film.get('overview'), str) or not film['overview'].strip():
            print('Film ozeti yok; atlaniyor.')
            continue
        if not isinstance(film.get('title'), str) or not film['title'].strip():
            print('Film adi yok; atlaniyor.')
            continue
        if type(film.get('id')) is not int or film['id'] <= 0:
            print('Film kimligi gecersiz; Gemini istegi gonderilmeden atlaniyor.')
            continue
        analysis = read_analysis_cache(film['id'], film['overview'], model)
        if analysis is None:
            if not allow_generation:
                raise ApiError('Bu film icin kayitli analiz yok. Yeni Gemini istegi gonderilmedi.')
            print('Gemini analizi bekleniyor (tek istek, en fazla 120 saniye)...', flush=True)
            with create_gemini_client() as client:
                analysis = gemini_analiz_et(client, film['overview'], model=model)
            write_analysis_cache(film['id'], film['overview'], model, analysis)
            all_cached = False
        else:
            print('Kayitli analiz kullaniliyor; yeni Gemini istegi gonderilmedi.')
        document = movie_document(film, analysis)
        documents.append(save_movie_document(document, model))
        print(f"Film analizi hazir. Radar skoru: {document['radarScore']}")
        print(f"Hedef kitle: {analysis['hedef_kitle']}")
        print(f"3 kelime: {analysis['uc_kelime']}")
        if write:
            publish_movie(settings, document)
    print('Islem tamamlandi.')
    return {'movies': documents, 'count': len(documents), 'cached': all_cached}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--write', action='store_true', help='Sanity kaydi olusturur.')
    modes.add_argument('--check', action='store_true', help='Gemini model erisimini ve Sanity okumasini kontrol eder.')
    modes.add_argument('--dry-run', action='store_true', help='Varsayilan: Sanity verilerini degistirmez.')
    parser.add_argument('--limit', type=int, default=1, help='Film sayisi (varsayilan: 1).')
    parser.add_argument('--model', help='Gemini modelini bu calistirma icin sec.')
    parser.add_argument('--cache-only', action='store_true', help='Yalnizca kayitli analiz; yeni Gemini istegi gondermez.')
    parser.add_argument('--next', action='store_true', help='Daha once analiz edilen filmleri atlayarak farkli film sec.')
    args = parser.parse_args()
    if args.limit < 1:
        parser.error('--limit en az 1 olmali.')
    if args.model is not None and (not args.model.strip() or not all(c.isalnum() or c in '-_./' for c in args.model)):
        parser.error('--model gecersiz.')
    load_settings()
    if args.check:
        with create_gemini_client() as client:
            check_gemini_model(client, model=args.model or gemini_model())
        check_sanity(sanity_settings())
        return
    analyze_movies(args.limit, args.model, write=args.write, allow_generation=not args.cache_only, next_unanalyzed=args.next)


if __name__ == '__main__':
    try:
        main()
    except ApiError as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
