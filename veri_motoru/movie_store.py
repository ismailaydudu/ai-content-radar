"""Local movie results for the frontend; credentials are never persisted."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile

from api_utils import ApiError, validate_analysis

STORE_PATH = Path(__file__).resolve().parent / '.cache' / 'movies.json'


def clean_movie(document):
    if not isinstance(document, dict) or type(document.get('tmdbId')) is not int or document['tmdbId'] <= 0:
        raise ApiError('Yerel film kaydi gecersiz.')
    for field in ('title', 'overview', 'model', 'analyzedAt'):
        if not isinstance(document.get(field), str) or not document[field].strip():
            raise ApiError('Yerel film kaydi eksik.')
    analysis = validate_analysis({
        'hedef_kitle': document.get('targetAudience'),
        'uc_kelime': document.get('threeWordSummary'), 'skor': document.get('radarScore'),
    })
    return {
        'tmdbId': document['tmdbId'], 'title': document['title'], 'overview': document['overview'],
        'model': document['model'], 'analyzedAt': document['analyzedAt'],
        'targetAudience': analysis['hedef_kitle'], 'threeWordSummary': analysis['uc_kelime'],
        'radarScore': analysis['skor'],
    }


def read_movie_documents():
    try:
        with STORE_PATH.open(encoding='utf-8') as handle:
            documents = json.load(handle)
        if not isinstance(documents, list):
            raise ValueError
        return [clean_movie(document) for document in documents]
    except FileNotFoundError:
        return []
    except (OSError, ValueError, ApiError):
        raise ApiError('Yerel film sonuclari okunamadi; dosya erisimini veya kayit bicimini kontrol edin.') from None


def save_movie_document(document, model):
    documents = read_movie_documents()
    previous = next((item for item in documents if item['tmdbId'] == document['tmdbId'] and item['model'] == model), None)
    timestamp = previous['analyzedAt'] if previous else datetime.now(timezone.utc).isoformat()
    movie = clean_movie({**document, 'model': model, 'analyzedAt': timestamp})
    documents = [item for item in documents if not (item['tmdbId'] == movie['tmdbId'] and item['model'] == model)]
    documents.insert(0, movie)
    temporary_path = None
    try:
        STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=STORE_PATH.parent, delete=False) as handle:
            temporary_path = Path(handle.name)
            json.dump(documents, handle, ensure_ascii=False)
        os.replace(temporary_path, STORE_PATH)
    except OSError:
        raise ApiError('Yerel film sonuclari kaydedilemedi.') from None
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
    return movie
