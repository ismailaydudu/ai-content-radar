"""Offline HTTP regressions: no external API requests or content mutations."""
from concurrent.futures import ThreadPoolExecutor
import http.client
import json
import os
from threading import Event, Thread
import unittest
from unittest.mock import patch

from api_utils import ApiError
import server


MOVIE = {
    '_type': 'movie', 'tmdbId': 42, 'title': 'Test film', 'overview': 'Test overview',
    'targetAudience': 'Film sevenler', 'threeWordSummary': 'Aksiyon, Gerilim, Macera',
    'radarScore': 8,
}
RESULT = {'movies': [MOVIE], 'count': 1, 'cached': True}


class ServerTests(unittest.TestCase):
    def setUp(self):
        # The HTTP client below only connects to the ephemeral loopback server.
        # These mocks prevent accidental external API traffic in all route tests.
        self.start_patch(patch('requests.get'))
        self.post = self.start_patch(patch('requests.post'))
        self.generate = self.start_patch(patch.object(server, 'analyze_movies', return_value=RESULT))
        self.read_movies = self.start_patch(patch.object(server, 'read_movie_documents', return_value=[MOVIE]))
        self.start_patch(patch.object(server, 'load_settings'))
        self.start_patch(patch.dict(os.environ, {}, clear=True))
        self.httpd = server.create_server(port=0)
        self.thread = Thread(target=self.httpd.serve_forever, kwargs={'poll_interval': 0.01}, daemon=True)
        self.thread.start()

    def start_patch(self, patcher):
        self.addCleanup(patcher.stop)
        return patcher.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)
        self.post.assert_not_called()

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.httpd.server_port, timeout=3)
        try:
            connection.request(method, path, body=body, headers=headers or {})
            response = connection.getresponse()
            return response.status, json.loads(response.read().decode('utf-8'))
        finally:
            connection.close()

    def analyze(self, body='{}', headers=None):
        return self.request('POST', '/api/analyze', body, headers or {'Content-Type': 'application/json'})

    def test_read_endpoints_never_trigger_generation(self):
        status, health = self.request('GET', '/health')
        self.assertEqual(status, 200)
        self.assertEqual(health['status'], 'ok')
        self.assertFalse(health['geminiConfigured'])
        self.assertFalse(health['tmdbConfigured'])
        self.assertFalse(health['sanityConfigured'])
        status, movies = self.request('GET', '/api/movies')
        self.assertEqual(status, 200)
        self.assertEqual(movies, {'movies': [MOVIE], 'count': 1})
        self.generate.assert_not_called()

    def test_cache_only_post_forbids_generation(self):
        status, result = self.analyze(body='{"cacheOnly":true}')
        self.assertEqual(status, 200)
        self.assertEqual(result, RESULT)
        self.generate.assert_called_once_with(
            limit=1, model='gemini-3.5-flash-lite', write=False, allow_generation=False,
        )

    def test_cache_only_numeric_flag_is_rejected(self):
        self.assertEqual(self.analyze(body='{"cacheOnly":1}')[0], 400)
        self.generate.assert_not_called()

    def test_health_reports_configuration_without_secret_values(self):
        settings = {name: 'FAKE_SECRET' for name in (
            'GEMINI_API_KEY', 'TMDB_API_KEY', 'SANITY_PROJECT_ID', 'SANITY_API_TOKEN',
        )}
        with patch.dict(os.environ, settings, clear=True):
            status, health = self.request('GET', '/health')
        self.assertEqual(status, 200)
        self.assertTrue(health['geminiConfigured'])
        self.assertTrue(health['tmdbConfigured'])
        self.assertTrue(health['sanityConfigured'])
        self.assertNotIn('FAKE_SECRET', json.dumps(health))
        self.generate.assert_not_called()

    def test_post_invokes_exactly_one_read_only_analysis(self):
        status, result = self.analyze(headers={
            'Content-Type': 'application/json', 'Origin': 'http://localhost:3000',
        })
        self.assertEqual(status, 200)
        self.assertEqual(result, RESULT)
        self.generate.assert_called_once_with(
            limit=1, model='gemini-3.5-flash-lite', write=False, next_unanalyzed=True,
        )

    def test_invalid_requests_do_not_consume_quota(self):
        for body in ('not-json', '[]', 'null', '{"write":true}', '{"limit":3}', '{"model":"other"}'):
            with self.subTest(body=body[:30]):
                self.assertEqual(self.analyze(body)[0], 400)
        self.assertEqual(self.analyze(headers={'Content-Type': 'text/plain'})[0], 400)
        # No payload follows invalid lengths: sending unread bytes can make
        # Windows reset the socket before the client's 400 response is read.
        for length in ('bad', '1025', '0', '-1'):
            with self.subTest(length=length):
                self.assertEqual(self.request('POST', '/api/analyze', headers={
                    'Content-Type': 'application/json', 'Content-Length': length,
                })[0], 400)
        self.generate.assert_not_called()

    def test_unknown_routes_and_untrusted_origin_do_not_consume_quota(self):
        self.assertEqual(self.request('GET', '/missing')[0], 404)
        self.assertEqual(self.request('POST', '/missing', '{}')[0], 404)
        self.assertEqual(self.analyze(headers={
            'Content-Type': 'application/json', 'Origin': 'https://example.invalid',
        })[0], 403)
        self.generate.assert_not_called()

    def test_analysis_failure_is_not_retried_and_releases_lock(self):
        self.generate.side_effect = [ApiError('Gemini HTTP 503: Servis kullanilamiyor.'), RESULT]
        status, error = self.analyze()
        self.assertEqual(status, 502)
        self.assertIn('503', error['error'])
        self.assertEqual(self.generate.call_count, 1)
        self.assertEqual(self.analyze()[0], 200)
        self.assertEqual(self.generate.call_count, 2)

    def test_unexpected_error_hides_internal_exception(self):
        self.generate.side_effect = RuntimeError('FAKE_SECRET in internal URL')
        status, error = self.analyze()
        self.assertEqual(status, 500)
        self.assertNotIn('FAKE_SECRET', json.dumps(error))
        self.assertEqual(self.generate.call_count, 1)

    def test_concurrent_click_is_rejected_without_second_analysis(self):
        entered, finish = Event(), Event()

        def blocked_analysis(**kwargs):
            entered.set()
            if not finish.wait(timeout=2):
                raise AssertionError('Test did not release analysis.')
            return RESULT

        self.generate.side_effect = blocked_analysis
        with ThreadPoolExecutor(max_workers=1) as pool:
            first = pool.submit(self.analyze)
            try:
                self.assertTrue(entered.wait(timeout=1))
                self.assertEqual(self.analyze()[0], 409)
                self.assertEqual(self.generate.call_count, 1)
            finally:
                finish.set()
            self.assertEqual(first.result(timeout=2)[0], 200)
        self.generate.assert_called_once_with(
            limit=1, model='gemini-3.5-flash-lite', write=False, next_unanalyzed=True,
        )


if __name__ == '__main__':
    unittest.main()
