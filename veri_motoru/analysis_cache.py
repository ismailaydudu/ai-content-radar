"""Local cache of validated analyses; no credentials or network requests."""
import hashlib
import json
import os
from pathlib import Path
import tempfile

from api_utils import ApiError, validate_analysis


CACHE_DIR = Path(__file__).resolve().parent / '.cache' / 'analysis'


def cache_key(movie_id, overview, model):
    source = {'version': 1, 'tmdbId': movie_id, 'overview': overview, 'model': model}
    payload = json.dumps(source, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def read_analysis_cache(movie_id, overview, model):
    path = CACHE_DIR / f'{cache_key(movie_id, overview, model)}.json'
    try:
        with path.open(encoding='utf-8') as handle:
            return validate_analysis(json.load(handle))
    except (OSError, ValueError, UnicodeError, ApiError):
        return None


def write_analysis_cache(movie_id, overview, model, analysis):
    validated = validate_analysis(analysis)
    key = cache_key(movie_id, overview, model)
    temporary_path = None
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode='w', encoding='utf-8', dir=CACHE_DIR,
            prefix=f'.{key}.', suffix='.tmp', delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            json.dump(validated, handle, ensure_ascii=False)
        os.replace(temporary_path, CACHE_DIR / f'{key}.json')
    except OSError:
        raise ApiError('Analiz onbellegi kaydedilemedi; yerel dosya erisimini kontrol edin.') from None
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
