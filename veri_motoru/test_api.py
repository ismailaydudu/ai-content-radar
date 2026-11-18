"""Offline regression tests: no live API requests or Sanity writes."""
import contextlib
import importlib
import io
import os
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

import requests
from google.genai import errors

import api_utils as api
import tmdb_cek


VALID = {'hedef_kitle': 'Gerilim sevenler', 'uc_kelime': 'Aksiyon, Gerilim, Macera', 'skor': 8}


class ApiTests(unittest.TestCase):
    def test_import_does_not_call_apis(self):
        with patch('requests.get') as get, patch('requests.post') as post, patch.object(api.genai, 'Client') as client:
            importlib.reload(tmdb_cek)
            importlib.import_module('ai_analiz')
            get.assert_not_called()
            post.assert_not_called()
            client.assert_not_called()

    def test_invalid_analysis_is_rejected_without_coercion(self):
        for score in (True, '8', 8.5, 0, 11, None):
            with self.subTest(score=score), self.assertRaises(api.ApiError):
                api.validate_analysis({**VALID, 'skor': score})
        for words in ('Aksiyon, Gerilim', 'Aksiyon, Cok Gerilim, Macera', 'Aksiyon, , Macera'):
            with self.subTest(words=words), self.assertRaises(api.ApiError):
                api.validate_analysis({**VALID, 'uc_kelime': words})
        self.assertEqual(api.validate_analysis(VALID), VALID)

    def test_http_errors_hide_key_and_body(self):
        response = MagicMock(status_code=403)
        response.text = 'FAKE_SECRET'
        with patch('requests.get', return_value=response):
            with self.assertRaises(api.ApiError) as caught:
                api.get_json('https://example.invalid?api_key=FAKE_SECRET', 'TMDB')
        self.assertIn('403', str(caught.exception))
        self.assertNotIn('FAKE_SECRET', str(caught.exception))
        with patch('requests.get', side_effect=requests.ConnectionError('api_key=FAKE_SECRET')):
            with self.assertRaises(api.ApiError) as caught:
                api.get_json('https://example.invalid', 'TMDB')
        self.assertNotIn('FAKE_SECRET', str(caught.exception))

    def test_gemini_success_disables_afc(self):
        client = MagicMock()
        response = SimpleNamespace(text='{"hedef_kitle":"Gerilim sevenler","uc_kelime":"Aksiyon, Gerilim, Macera","skor":8}')
        client.models.generate_content.return_value = response
        self.assertEqual(api.gemini_analiz_et(client, 'Ozet'), VALID)
        config = client.models.generate_content.call_args.kwargs['config']
        self.assertTrue(config.automatic_function_calling.disable)
        self.assertEqual(client.models.generate_content.call_count, 1)

    def test_transport_errors_are_distinct_and_hide_secrets(self):
        for error_type, expected in (
            (requests.Timeout, 'zaman asimi'),
            (requests.exceptions.SSLError, 'TLS/sertifika'),
            (requests.ConnectionError, 'DNS'),
        ):
            with self.subTest(error_type=error_type), \
                 patch('requests.get', side_effect=error_type('api_key=FAKE_SECRET')), \
                 self.assertRaises(api.ApiError) as caught:
                api.get_json('https://example.invalid', 'TMDB')
            self.assertIn(expected, str(caught.exception))
            self.assertNotIn('FAKE_SECRET', str(caught.exception))

    def test_gemini_errors_never_retry(self):
        for status in (401, 403, 404, 429, 500, 502, 503, 504):
            client = MagicMock()
            error_type = errors.ServerError if status >= 500 else errors.ClientError
            client.models.generate_content.side_effect = error_type(status, {'error': {'message': 'FAKE_SECRET'}})
            with self.subTest(status=status), self.assertRaises(api.ApiError) as caught:
                api.gemini_analiz_et(client, 'Ozet')
            self.assertEqual(client.models.generate_content.call_count, 1)
            self.assertNotIn('FAKE_SECRET', str(caught.exception))

    def test_gemini_client_timeout_and_sdk_retry_budget(self):
        with patch.dict(os.environ, {'GEMINI_API_KEY': 'FAKE_SECRET'}, clear=True), \
             patch.object(api.genai, 'Client') as client:
            api.create_gemini_client()
        options = client.call_args.kwargs['http_options']
        self.assertEqual(options.timeout, 120000)
        self.assertEqual(options.retry_options.attempts, 1)

    def test_empty_and_malformed_gemini_responses(self):
        client = MagicMock()
        for text in ('', 'not json', '[]'):
            client.models.generate_content.return_value = SimpleNamespace(text=text)
            with self.subTest(text=text), self.assertRaises(api.ApiError):
                api.gemini_analiz_et(client, 'Ozet')

    def test_missing_env_and_invalid_sanity_config(self):
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(api.ApiError):
            api.create_gemini_client()
        for field, value in [('SANITY_PROJECT_ID', 'invalid/host'), ('SANITY_DATASET', ''), ('SANITY_API_VERSION', '2026-99-99')]:
            settings = {'SANITY_PROJECT_ID': 'abc123', 'SANITY_DATASET': 'production', 'SANITY_API_TOKEN': 'FAKE_SECRET'}
            settings[field] = value
            with self.subTest(field=field), patch.dict(os.environ, settings, clear=True), self.assertRaises(api.ApiError):
                api.sanity_settings()

    def test_dry_run_never_reads_or_writes_sanity(self):
        film = {'id': 42, 'title': 'İstanbul', 'overview': 'Ornek ozet'}
        for argv in (['tmdb_cek.py'], ['tmdb_cek.py', '--dry-run', '--limit', '1']):
            with patch('sys.argv', argv), patch.object(tmdb_cek, 'load_settings'), \
                 patch.object(tmdb_cek, 'required_env', return_value='FAKE_SECRET'), \
                 patch.object(tmdb_cek, 'get_json', return_value={'results': [film]}) as get, \
                 patch.object(tmdb_cek, 'create_gemini_client'), \
                 patch.object(tmdb_cek, 'gemini_analiz_et', return_value=VALID), \
                 patch.object(tmdb_cek, 'read_analysis_cache', return_value=None), \
                 patch.object(tmdb_cek, 'write_analysis_cache'), \
                 patch.object(tmdb_cek, 'save_movie_document', side_effect=lambda document, model: document), \
                 patch.object(tmdb_cek, 'sanity_settings') as settings, \
                 patch('requests.post') as post, contextlib.redirect_stdout(io.StringIO()):
                tmdb_cek.main()
            settings.assert_not_called()
            post.assert_not_called()
            self.assertEqual(get.call_count, 1)
            self.assertIn('themoviedb.org', get.call_args.args[0])
        document = tmdb_cek.movie_document(film, VALID)
        self.assertNotIn('_id', document)
        self.assertEqual(document['tmdbId'], 42)

    def test_cached_analysis_avoids_gemini_call(self):
        film = {'id': 42, 'title': 'Test', 'overview': 'Ornek ozet'}
        with patch('sys.argv', ['tmdb_cek.py', '--dry-run', '--model', 'gemini-3.5-flash-lite']), \
             patch.object(tmdb_cek, 'load_settings'), \
             patch.object(tmdb_cek, 'required_env', return_value='FAKE_SECRET'), \
             patch.object(tmdb_cek, 'get_json', return_value={'results': [film]}), \
             patch.object(tmdb_cek, 'create_gemini_client'), \
             patch.object(tmdb_cek, 'read_analysis_cache', return_value=VALID), \
             patch.object(tmdb_cek, 'write_analysis_cache') as save, \
             patch.object(tmdb_cek, 'save_movie_document', side_effect=lambda document, model: document), \
             patch.object(tmdb_cek, 'gemini_analiz_et') as generate, \
             patch('requests.post') as post, contextlib.redirect_stdout(io.StringIO()):
            tmdb_cek.main()
        generate.assert_not_called()
        save.assert_not_called()
        post.assert_not_called()

    def test_cache_only_missing_analysis_never_generates(self):
        film = {'id': 42, 'title': 'Test', 'overview': 'Ornek ozet'}
        with patch.object(tmdb_cek, 'load_settings'), \
             patch.object(tmdb_cek, 'required_env', return_value='FAKE_SECRET'), \
             patch.object(tmdb_cek, 'get_json', return_value={'results': [film]}), \
             patch.object(tmdb_cek, 'read_analysis_cache', return_value=None), \
             patch.object(tmdb_cek, 'create_gemini_client') as client, \
             patch.object(tmdb_cek, 'gemini_analiz_et') as generate, \
             contextlib.redirect_stdout(io.StringIO()), self.assertRaises(api.ApiError):
            tmdb_cek.analyze_movies(allow_generation=False)
        client.assert_not_called()
        generate.assert_not_called()

    def test_read_only_check_never_posts(self):
        with patch.object(tmdb_cek, 'get_json', return_value={'result': 0}), \
             patch('requests.post') as post, contextlib.redirect_stdout(io.StringIO()):
            tmdb_cek.check_sanity({'base_url': 'https://example.invalid/v2023-01-01', 'dataset': 'production', 'headers': {}})
        post.assert_not_called()

    def test_existing_movie_is_not_written(self):
        with patch.object(tmdb_cek, 'get_json', return_value={'result': 1}), \
             patch('requests.post') as post, contextlib.redirect_stdout(io.StringIO()):
            tmdb_cek.publish_movie({'base_url': 'https://example.invalid/v2023-01-01', 'dataset': 'production', 'headers': {}}, {'tmdbId': 42, 'title': 'İstanbul'})
        post.assert_not_called()


if __name__ == '__main__':
    unittest.main()
