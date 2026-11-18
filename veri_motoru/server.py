"""Persistent local backend. Reading pages never triggers Gemini generation."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import sys
from threading import Lock
from urllib.parse import urlsplit

from api_utils import ApiError, load_settings
from movie_store import read_movie_documents
from tmdb_cek import analyze_movies


def health_status():
    return {
        'status': 'ok', 'service': 'ai-content-radar',
        'geminiConfigured': bool(os.getenv('GEMINI_API_KEY', '').strip()),
        'tmdbConfigured': bool(os.getenv('TMDB_API_KEY', '').strip()),
        'sanityConfigured': bool(os.getenv('SANITY_PROJECT_ID', '').strip() and os.getenv('SANITY_API_TOKEN', '').strip()),
    }


class RadarServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address):
        super().__init__(address, RadarHandler)
        self.analysis_lock = Lock()


class RadarHandler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def log_message(self, format, *args):
        # Request URLs or exception strings must not expose credentials.
        pass

    def send_json(self, status, data):
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == '/health':
            self.send_json(200, health_status())
        elif path == '/api/movies':
            try:
                movies = read_movie_documents()
                self.send_json(200, {'movies': movies, 'count': len(movies)})
            except ApiError as error:
                self.send_json(500, {'error': str(error)})
        else:
            self.send_json(404, {'error': 'Adres bulunamadi.'})

    def do_POST(self):
        if urlsplit(self.path).path != '/api/analyze':
            self.send_json(404, {'error': 'Adres bulunamadi.'})
            return
        origin = self.headers.get('Origin')
        if origin and origin not in ('http://localhost:3000', 'http://127.0.0.1:3000'):
            self.send_json(403, {'error': 'Origin izni yok.'})
            return
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if length < 1 or length > 1024:
                raise ValueError
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict) or (body and not (set(body) == {'cacheOnly'} and body['cacheOnly'] is True)):
                raise ValueError
            if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                raise ValueError
        except (ValueError, UnicodeError, OSError):
            self.send_json(400, {'error': 'Istek application/json turunde bos nesne veya cacheOnly=true olmali.'})
            return
        if not self.server.analysis_lock.acquire(blocking=False):
            self.send_json(409, {'error': 'Bir analiz zaten devam ediyor; tamamlanmasini bekleyin.'})
            return
        try:
            options = {'limit': 1, 'model': 'gemini-3.5-flash-lite', 'write': False}
            if body.get('cacheOnly') is True:
                options['allow_generation'] = False
            else:
                options['next_unanalyzed'] = True
            result = analyze_movies(**options)
            self.send_json(200, result)
        except ApiError as error:
            self.send_json(502, {'error': str(error)})
        except Exception:
            self.send_json(500, {'error': 'Analiz tamamlanamadi. Yeni istek otomatik gonderilmedi.'})
        finally:
            self.server.analysis_lock.release()


def create_server(host='127.0.0.1', port=8000):
    load_settings()
    return RadarServer((host, port))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8000)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('--port 1-65535 olmali.')
    try:
        with create_server(port=args.port) as server:
            print(f'Backend hazir: http://127.0.0.1:{args.port}', flush=True)
            print('Sayfa acilinca Gemini istegi gonderilmez. Durdurmak icin Ctrl+C.', flush=True)
            server.serve_forever()
    except KeyboardInterrupt:
        print('Backend durduruldu.')
    except OSError:
        print('Backend baslatilamadi; port kullanimini veya yerel ag izinlerini kontrol edin.', file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
