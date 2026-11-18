"""Cache regression tests; no live APIs or Sanity operations."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import analysis_cache as cache
from api_utils import ApiError


VALID = {'hedef_kitle': 'Gerilim sevenler', 'uc_kelime': 'Aksiyon, Gerilim, Macera', 'skor': 8}


class AnalysisCacheTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.cache_patch = patch.object(cache, 'CACHE_DIR', Path(self.directory.name) / 'analysis')
        self.cache_patch.start()
        self.addCleanup(self.cache_patch.stop)

    def test_write_read_and_only_validated_fields_are_stored(self):
        self.assertIsNone(cache.read_analysis_cache(42, 'Film ozeti', 'model-a'))
        cache.write_analysis_cache(42, 'Film ozeti', 'model-a', {**VALID, 'unexpected': 'discard me'})
        self.assertEqual(cache.read_analysis_cache(42, 'Film ozeti', 'model-a'), VALID)
        path = cache.CACHE_DIR / f'{cache.cache_key(42, "Film ozeti", "model-a")}.json'
        self.assertEqual(json.loads(path.read_text(encoding='utf-8')), VALID)
        self.assertEqual(list(cache.CACHE_DIR.glob('*.tmp')), [])

    def test_source_changes_invalidate_cache(self):
        cache.write_analysis_cache(42, 'Film ozeti', 'model-a', VALID)
        for movie_id, overview, model in (
            (43, 'Film ozeti', 'model-a'),
            (42, 'Yeni ozet', 'model-a'),
            (42, 'Film ozeti', 'model-b'),
        ):
            with self.subTest(movie_id=movie_id, overview=overview, model=model):
                self.assertIsNone(cache.read_analysis_cache(movie_id, overview, model))

    def test_corrupt_invalid_and_unreadable_cache_is_a_miss(self):
        cache.CACHE_DIR.mkdir()
        path = cache.CACHE_DIR / f'{cache.cache_key(42, "Film ozeti", "model-a")}.json'
        for content in ('not json', '[]', '{}', json.dumps({**VALID, 'skor': True})):
            path.write_text(content, encoding='utf-8')
            with self.subTest(content=content):
                self.assertIsNone(cache.read_analysis_cache(42, 'Film ozeti', 'model-a'))
        path.write_bytes(b'\xff')
        self.assertIsNone(cache.read_analysis_cache(42, 'Film ozeti', 'model-a'))
        with patch.object(Path, 'open', side_effect=PermissionError('FAKE_SECRET')):
            self.assertIsNone(cache.read_analysis_cache(42, 'Film ozeti', 'model-a'))

    def test_invalid_analysis_never_creates_cache(self):
        for invalid in (None, {}, {**VALID, 'skor': 11}, {**VALID, 'uc_kelime': 'Only two'}):
            with self.subTest(analysis=invalid), self.assertRaises(ApiError):
                cache.write_analysis_cache(42, 'Film ozeti', 'model-a', invalid)
        self.assertFalse(cache.CACHE_DIR.exists())

    def test_failed_atomic_write_keeps_previous_cache_and_hides_raw_error(self):
        cache.write_analysis_cache(42, 'Film ozeti', 'model-a', VALID)
        with patch.object(cache.os, 'replace', side_effect=OSError('FAKE_SECRET')):
            with self.assertRaises(ApiError) as caught:
                cache.write_analysis_cache(42, 'Film ozeti', 'model-a', {**VALID, 'skor': 9})
        self.assertNotIn('FAKE_SECRET', str(caught.exception))
        self.assertEqual(cache.read_analysis_cache(42, 'Film ozeti', 'model-a'), VALID)
        self.assertEqual(list(cache.CACHE_DIR.glob('*.tmp')), [])

    def test_cache_key_is_safe_for_file_names(self):
        key = cache.cache_key(42, 'Film: Istanbul / ..', 'model/a')
        self.assertRegex(key, r'^[a-f0-9]{64}$')
        self.assertEqual(key, cache.cache_key(42, 'Film: Istanbul / ..', 'model/a'))


if __name__ == '__main__':
    unittest.main()
