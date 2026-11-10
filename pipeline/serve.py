#!/usr/bin/env python3
"""
serve.py: serves the Songbook Player like `python3 -m http.server`, plus the 🎸 Remove guitar button.

  ~/.venvs/demucs/bin/python pipeline/serve.py            # then open http://localhost:8000/index.html
  ~/.venvs/demucs/bin/python pipeline/serve.py 8001       # another port

Endpoints (localhost only):
  GET  /api/health   → {"ok":true,"demucs":bool,"ffmpeg":bool}
  POST /api/isolate  → body = WAV of a take; returns the guitar stem (removes the song the phone heard in the room)
  POST /api/backing  → body = the song file; headers X-Filename, X-Title, X-Artist (URL-encoded), X-Guide
                       returns the finished .m4a (also saved to ~/Downloads/Songbook Backing Tracks)
"""
import http.server, importlib.util, json, os, shutil, subprocess, sys, tempfile, threading, urllib.parse

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
                                    "ffmpeg": shutil.which("ffmpeg") is not None, "render": True, "busy": JOB.locked()})
        return super().do_GET()

    def do_POST(self):
        p = self.path.split("?")[0]
        if p.startswith("/api/render/"):
            return self._render(p[len("/api/render/"):])
        if p == "/api/isolate":
            return self._isolate()
        if p != "/api/backing":
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


def _isolate(self):
    """POST /api/isolate: body = WAV of a take (phone video sound). Demucs pulls the guitar out, so the song playing
    in the room (which the phone also heard) doesn't bury it. Returns the guitar stem as WAV."""
    if self.client_address[0] not in ("127.0.0.1", "::1"):
        return self._json(403, {"error": "local use only"})
    body = _read_body(self, MAX_BYTES)
    if not body: return self._json(400, {"error": "send a WAV"})
    if not JOB.acquire(blocking=False):
        return self._json(409, {"error": "busy, try again in a minute"})
    tmp = tempfile.mkdtemp(prefix="sb-iso-")
    try:
        src = os.path.join(tmp, "take.wav"); open(src, "wb").write(body)
        r = subprocess.run([sys.executable, "-m", "demucs", "-n", "htdemucs_6s", "--two-stems", "guitar", "-o", tmp, src],
                           capture_output=True, text=True)
        out = os.path.join(tmp, "htdemucs_6s", "take", "guitar.wav")
        if r.returncode or not os.path.exists(out):
            return self._json(500, {"error": "demucs: " + (r.stderr or "")[-300:]})
        data = open(out, "rb").read()
        self.send_response(200); self.send_header("Content-Type", "audio/wav"); self.send_header("Content-Length", str(len(data)))
        self.end_headers(); self.wfile.write(data)
    finally:
        JOB.release(); shutil.rmtree(tmp, ignore_errors=True)


Handler._isolate = _isolate

RENDERS = {}
RENDER_OUT = os.path.expanduser("~/Downloads/Songbook Videos")


def _read_body(handler, limit):
    n = int(handler.headers.get("Content-Length") or 0)
    if not 0 < n <= limit: return None
    out, left = bytearray(), n
    while left:
        c = handler.rfile.read(min(left, 1 << 20))
        if not c: break
        out += c; left -= len(c)
    return bytes(out)


def _render(self, step):
    """Full-quality lyric videos (mandatory path after a lyrics upload, when this server is running):
    start (original video) → frame (transparent overlay PNGs at 10 fps, drawn by the app) → audio (guitar-fixed + backing WAV,
    rendered offline by the app) → finish: ffmpeg overlays the frames on the ORIGINAL video at its own frame rate, H.264 8 Mbps."""
    if self.client_address[0] not in ("127.0.0.1", "::1"):
        return self._json(403, {"error": "local use only"})
    q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(self.path).query))
    if step == "start":
        body = _read_body(self, 900 * 1024 * 1024)
        if body is None: return self._json(400, {"error": "send the video (up to 900 MB)"})
        rid = os.urandom(6).hex(); d = tempfile.mkdtemp(prefix="sb-render-"); os.makedirs(d + "/ov")
        ext = os.path.splitext(q.get("name", "video.mp4"))[1].lower() or ".mp4"
        open(d + "/src" + ext, "wb").write(body)
        RENDERS[rid] = {"dir": d, "src": d + "/src" + ext, "name": os.path.splitext(os.path.basename(q.get("name", "video")))[0]}
        info = {}
        try:
            pr = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height,avg_frame_rate:stream_side_data=rotation:format=duration",
                                 "-of", "json", d + "/src" + ext], capture_output=True, text=True, timeout=60)
            j = json.loads(pr.stdout or "{}"); s0 = (j.get("streams") or [{}])[0]; w, h = int(s0.get("width", 0)), int(s0.get("height", 0))
            rot = abs(int(float(((s0.get("side_data_list") or [{}])[0]).get("rotation", 0) or 0)))
            if rot in (90, 270): w, h = h, w
            info = {"w": w, "h": h, "dur": float((j.get("format") or {}).get("duration", 0) or 0)}
        except Exception: pass
        return self._json(200, {"id": rid, **info})
    r = RENDERS.get(q.get("id", ""))
    if not r: return self._json(404, {"error": "unknown render"})
    if step == "frame":
        body = _read_body(self, 20 * 1024 * 1024)
        if body is None: return self._json(400, {"error": "empty frame"})
        open(r["dir"] + "/ov/o_%05d.png" % int(q.get("i", "0")), "wb").write(body); return self._json(200, {"ok": True})
    if step == "audio":
        body = _read_body(self, 400 * 1024 * 1024)
        if body is None: return self._json(400, {"error": "empty audio"})
        open(r["dir"] + "/audio.wav", "wb").write(body); return self._json(200, {"ok": True})
    if step == "finish":
        w = max(320, min(3840, int(q.get("w", "1280")))); fps = float(q.get("ovfps", "10")); label = q.get("label", "lyrics")
        os.makedirs(RENDER_OUT, exist_ok=True)
        out = os.path.join(RENDER_OUT, mb.clean_name(f"{r['name']} ({label})") + ".mp4")
        have_audio = os.path.exists(r["dir"] + "/audio.wav")
        cmd = ["ffmpeg", "-loglevel", "error", "-y", "-i", r["src"], "-framerate", str(fps), "-i", r["dir"] + "/ov/o_%05d.png"]
        if have_audio: cmd += ["-i", r["dir"] + "/audio.wav"]
        cmd += ["-filter_complex", f"[0:v:0]scale={w}:-2,format=yuv420p[b];[1:v]format=rgba,scale={w}:-2[o];[b][o]overlay=0:0:eof_action=pass,format=yuv420p[v]",
                "-map", "[v]", "-map", "2:a:0" if have_audio else "0:a:0?"]
        enc = ["-c:v", "h264_videotoolbox", "-b:v", "8M", "-profile:v", "high"] if sys.platform == "darwin" else ["-c:v", "libx264", "-preset", "medium", "-crf", "19"]
        cmd += enc + ["-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-shortest", out]
        p = subprocess.run(cmd, capture_output=True, text=True)
        if p.returncode != 0:
            return self._json(500, {"error": "ffmpeg: " + (p.stderr or "")[-600:]})
        data = open(out, "rb").read(); shutil.rmtree(r["dir"], ignore_errors=True); RENDERS.pop(q["id"], None)
        self.send_response(200); self.send_header("Content-Type", "video/mp4"); self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Filename", urllib.parse.quote(os.path.basename(out))); self.end_headers(); self.wfile.write(data); return
    return self._json(404, {"error": "unknown step"})


Handler._render = _render


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
    ok = importlib.util.find_spec("demucs") is not None
    print(f"Songbook Player on http://localhost:{port}/index.html  ·  🎸 Remove guitar: {'ready' if ok else 'needs demucs (run with ~/.venvs/demucs/bin/python)'}", flush=True)
    try: srv.serve_forever()
    except KeyboardInterrupt: pass


if __name__ == "__main__":
    main()
