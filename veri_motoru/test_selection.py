"""Film selection regressions: all external APIs and writes are mocked."""
import contextlib
import io
import unittest
from unittest.mock import patch

from api_utils import ApiError
import tmdb_cek


MODEL = 'gemini-3.5-flash-lite'
VALID = {'hedef_kitle': 'Gerilim sevenler', 'uc_kelime': 'Aksiyon, Gerilim, Macera', 'skor': 8}


def film(movie_id):
    return {'id': movie_id, 'title': f'Film {movie_id}', 'overview': f'Ozet {movie_id}'}


class MovieSelectionTests(unittest.TestCase):
    def setUp(self):
        self.stored = [{'tmdbId': 42, 'model': 'previous-model'}]
        self.start_patch(patch.object(tmdb_cek, 'load_settings'))
        self.start_patch(patch.object(tmdb_cek, 'required_env', return_value='FAKE_SECRET'))
        self.read_store = self.start_patch(patch.object(
            tmdb_cek, 'read_movie_documents', side_effect=lambda: list(self.stored), create=True,
        ))
        self.get_movies = self.start_patch(patch.object(
            tmdb_cek, 'get_json', return_value={'results': [film(42), film(43), film(44)], 'total_pages': 1},
        ))
        self.read_cache = self.start_patch(patch.object(tmdb_cek, 'read_analysis_cache', return_value=None))
        self.write_cache = self.start_patch(patch.object(tmdb_cek, 'write_analysis_cache'))
        self.client = self.start_patch(patch.object(tmdb_cek, 'create_gemini_client'))
        self.generate = self.start_patch(patch.object(tmdb_cek, 'gemini_analiz_et', return_value=VALID))
        self.save = self.start_patch(patch.object(tmdb_cek, 'save_movie_document', side_effect=self.save_locally))
        self.settings = self.start_patch(patch.object(tmdb_cek, 'sanity_settings'))
        self.publish = self.start_patch(patch.object(tmdb_cek, 'publish_movie'))
        self.post = self.start_patch(patch('requests.post'))
        self.raw_get = self.start_patch(patch('requests.get'))
        self.start_patch(contextlib.redirect_stdout(io.StringIO()))

    def start_patch(self, patcher):
        value = patcher.__enter__()
        self.addCleanup(patcher.__exit__, None, None, None)
        return value

    def save_locally(self, document, model):
        saved = {**document, 'model': model}
        self.stored.append(saved)
        return saved

    def tearDown(self):
        self.settings.assert_not_called()
        self.publish.assert_not_called()
        self.post.assert_not_called()
        self.raw_get.assert_not_called()

    def analyze_next(self, **options):
        return tmdb_cek.analyze_movies(limit=1, model=MODEL, write=False, next_unanalyzed=True, **options)

    def test_next_film_skips_analyzed_id_even_with_different_model(self):
        result = self.analyze_next()
        self.assertEqual([movie['tmdbId'] for movie in result['movies']], [43])
        self.assertEqual(result['count'], 1)
        self.assertFalse(result['cached'])
        self.generate.assert_called_once()
        self.assertEqual(self.generate.call_args.args[1], 'Ozet 43')
        self.assertEqual(self.client.call_count, 1)
        self.write_cache.assert_called_once_with(43, 'Ozet 43', MODEL, VALID)

    def test_consecutive_clicks_select_different_unanalyzed_films(self):
        first = self.analyze_next()
        second = self.analyze_next()
        self.assertEqual(first['movies'][0]['tmdbId'], 43)
        self.assertEqual(second['movies'][0]['tmdbId'], 44)
        self.assertEqual(self.generate.call_count, 2)
        self.assertEqual([call.args[1] for call in self.generate.call_args_list], ['Ozet 43', 'Ozet 44'])

    def test_invalid_candidates_do_not_consume_the_one_film_limit(self):
        self.get_movies.return_value = {
            'results': [None, {}, {**film(40), 'overview': ' '}, {**film(41), 'title': ' '},
                        {**film(43), 'id': True}, {**film(43), 'id': -1}, film(42), film(43)],
            'total_pages': 1,
        }
        result = self.analyze_next()
        self.assertEqual(result['movies'][0]['tmdbId'], 43)
        self.generate.assert_called_once()
        self.assertEqual(self.generate.call_args.args[1], 'Ozet 43')

    def test_next_page_is_read_when_first_page_has_no_new_film(self):
        self.get_movies.side_effect = [
            {'results': [film(42)], 'total_pages': 3},
            {'results': [None], 'total_pages': 3},
            {'results': [film(43)], 'total_pages': 3},
        ]
        result = self.analyze_next()
        self.assertEqual(result['movies'][0]['tmdbId'], 43)
        self.assertEqual([call.kwargs['params']['page'] for call in self.get_movies.call_args_list], [1, 2, 3])
        self.generate.assert_called_once()

    def test_exhausted_list_does_not_generate_or_save(self):
        self.get_movies.return_value = {'results': [film(42)], 'total_pages': 1}
        with self.assertRaises(ApiError):
            self.analyze_next()
        self.get_movies.assert_called_once()
        self.client.assert_not_called()
        self.generate.assert_not_called()
        self.write_cache.assert_not_called()
        self.save.assert_not_called()

    def test_search_is_bounded_even_for_many_pages_without_a_new_film(self):
        self.get_movies.return_value = {'results': [film(42)], 'total_pages': 999}
        with self.assertRaises(ApiError):
            self.analyze_next()
        self.assertEqual([call.kwargs['params']['page'] for call in self.get_movies.call_args_list], [1, 2, 3, 4, 5])
        self.client.assert_not_called()
        self.generate.assert_not_called()
        self.save.assert_not_called()

    def test_unseen_movie_reuses_its_existing_analysis_without_generation(self):
        self.read_cache.return_value = VALID
        result = self.analyze_next()
        self.assertEqual(result['movies'][0]['tmdbId'], 43)
        self.assertTrue(result['cached'])
        self.client.assert_not_called()
        self.generate.assert_not_called()
        self.write_cache.assert_not_called()
        self.save.assert_called_once()

    def test_next_selection_cannot_override_generation_disabled(self):
        with self.assertRaises(ApiError):
            self.analyze_next(allow_generation=False)
        self.client.assert_not_called()
        self.generate.assert_not_called()
        self.write_cache.assert_not_called()
        self.save.assert_not_called()

    def test_default_cached_selection_still_returns_first_film_without_generation(self):
        self.read_cache.return_value = VALID
        result = tmdb_cek.analyze_movies(limit=1, model=MODEL, write=False, allow_generation=False)
        self.assertEqual(result['movies'][0]['tmdbId'], 42)
        self.assertTrue(result['cached'])
        self.client.assert_not_called()
        self.generate.assert_not_called()
        self.write_cache.assert_not_called()
        self.read_store.assert_not_called()


if __name__ == '__main__':
    unittest.main()
