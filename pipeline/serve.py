#!/usr/bin/env python3
"""
serve.py: serves the Songbook Player like `python3 -m http.server`, plus the 🎸 Remove guitar button.

  ~/.venvs/demucs/bin/python pipeline/serve.py            # then open http://localhost:8000/index.html
  ~/.venvs/demucs/bin/python pipeline/serve.py 8001       # another port

Endpoints (localhost only):
  GET  /api/health   → {"ok":true,"demucs":bool,"ffmpeg":bool}
  POST /api/backing  → body = the song file; headers X-Filename, X-Title, X-Artist (URL-encoded), X-Guide
                       returns the finished .m4a (also saved to ~/Downloads/Songbook Backing Tracks)
"""
import http.server, importlib.util, json, os, shutil, sys, tempfile, threading, urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import make_backing as mb  # noqa: E402

JOB = threading.Lock()
MAX_BYTES = 300 * 1024 * 1024


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=ROOT, **k)

    def end_headers(self):
        if self.path.split("?")[0].endswith((".html", ".json", ".txt")):
            self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def _json(self, code, obj):
        b = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(b)))
        self.end_headers(); self.wfile.write(b)

    def do_GET(self):
        if self.path.split("?")[0] == "/api/health":
            return self._json(200, {"ok": True, "demucs": importlib.util.find_spec("demucs") is not None,
                                    "ffmpeg": shutil.which("ffmpeg") is not None, "busy": JOB.locked()})
        return super().do_GET()

    def do_POST(self):
        if self.path.split("?")[0] != "/api/backing":
            return self._json(404, {"error": "not found"})
        if self.client_address[0] not in ("127.0.0.1", "::1"):
            return self._json(403, {"error": "local use only"})
        n = int(self.headers.get("Content-Length") or 0)
        if not 0 < n <= MAX_BYTES:
            return self._json(400, {"error": "send the song file (up to 300 MB)"})
        h = lambda k: urllib.parse.unquote(self.headers.get(k) or "").strip() or None
        name = os.path.basename(h("X-Filename") or "song.mp3")
        try: guide = max(0.0, min(1.0, float(h("X-Guide") or 0.5)))
        except ValueError: guide = 0.5
        if not JOB.acquire(blocking=False):
            return self._json(409, {"error": "already making a backing track, try again in a minute"})
        tmp = tempfile.mkdtemp(prefix="sb-upload-")
        try:
            src = os.path.join(tmp, name)
            with open(src, "wb") as f:
                left = n
                while left:
                    chunk = self.rfile.read(min(left, 1 << 20))
                    if not chunk: break
                    f.write(chunk); left -= len(chunk)
            try:
                info = mb.make_backing(src, title=h("X-Title"), artist=h("X-Artist"), guide=guide, log=lambda m: print("  " + m, flush=True))
            except SystemExit as e:
                return self._json(500, {"error": str(e)})
            data = open(info["output"], "rb").read()
            self.send_response(200)
            self.send_header("Content-Type", "audio/mp4"); self.send_header("Content-Length", str(len(data)))
            self.send_header("X-Filename", urllib.parse.quote(os.path.basename(info["output"])))
            self.send_header("X-Info", urllib.parse.quote(json.dumps(info, ensure_ascii=False)))
            self.send_header("Access-Control-Expose-Headers", "X-Filename, X-Info")
            self.end_headers(); self.wfile.write(data)
        finally:
            JOB.release(); shutil.rmtree(tmp, ignore_errors=True)


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
    ok = importlib.util.find_spec("demucs") is not None
    print(f"Songbook Player on http://localhost:{port}/index.html  ·  🎸 Remove guitar: {'ready' if ok else 'needs demucs (run with ~/.venvs/demucs/bin/python)'}", flush=True)
    try: srv.serve_forever()
    except KeyboardInterrupt: pass


if __name__ == "__main__":
    main()
