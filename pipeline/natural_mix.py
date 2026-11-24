#!/usr/bin/env python3
"""natural_mix.py — the "natural" video sound (chosen 2026-11-24 on Nenu Nuvvantu, version C).

Keeps your phone's own recording, in which your guitar and the song playing in the room are naturally in sync,
and only rebalances it with its own Demucs stems. The stems come from the same recording (sample-exact), and
the original sound stays underneath, so nothing echoes, smears or sounds "separated":
    out = phone + SONG·(vocals+bass+drums+piano+other) + VOX·vocals − GTR·guitar
then a light clean-up (rumble cut, −1.5 dB at 4.2 kHz, gentle 1.8:1 compression), −16 dB level, −1 dBFS limiter.
No clean song file is layered on top: a song copy that is even 20 ms off makes the mix hollow / echoey.

On Nenu Nuvvantu (IMG_6592): guitar loudest 82 % → 28 % of seconds, singing −2.9 → +3.1 dB over the guitar.

  ~/.venvs/demucs/bin/python pipeline/natural_mix.py RECORDING.(mov|mp4|wav) OUT.wav
"""
import json, os, shutil, subprocess, sys, tempfile
import numpy as np, soundfile as sf

SR = 44100
SONG, VOX, GTR = 0.35, 0.20, 0.10
CLEAN = "highpass=f=60,equalizer=f=4200:t=q:w=1.0:g=-1.5,acompressor=threshold=0.12:ratio=1.8:attack=15:release=250:knee=6"


def _ff(src, dst, af=None):
    p = subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", src, "-vn", "-ac", "2", "-ar", str(SR)] + (["-af", af] if af else []) + ["-c:a", "pcm_f32le", dst],
                       capture_output=True, text=True)
    if p.returncode: raise RuntimeError("ffmpeg: " + p.stderr[-300:])


def _active(x):
    w = SR // 4; n = len(x) // w
    r = np.sqrt((x[:n * w].reshape(n, w, -1) ** 2).mean(axis=(1, 2))); r = np.sort(r[r > 1e-5])
    return float(np.sqrt((r[int(len(r) * .3):] ** 2).mean())) if len(r) else 0.0


def _db(a, b):
    return 20 * np.log10((a + 1e-9) / (b + 1e-9))


def natural(src, out_wav, song=SONG, vox=VOX, gtr=GTR):
    """Write the natural mix of the recording `src` to `out_wav` (16-bit). Returns a small report dict."""
    tmp = tempfile.mkdtemp(prefix="sb-natural-")
    try:
        rec = os.path.join(tmp, "rec.wav"); _ff(src, rec)
        p = subprocess.run([sys.executable, "-m", "demucs", "-n", "htdemucs_6s", "-o", tmp, rec], capture_output=True, text=True)
        d = os.path.join(tmp, "htdemucs_6s", "rec")
        if p.returncode or not os.path.exists(os.path.join(d, "guitar.wav")):
            raise RuntimeError("demucs: " + (p.stderr or "")[-300:])
        orig = sf.read(rec, always_2d=True, dtype="float32")[0]
        st = {k: sf.read(os.path.join(d, k + ".wav"), always_2d=True, dtype="float32")[0] for k in ("vocals", "bass", "drums", "piano", "other", "guitar")}
        n = min(len(orig), *(len(v) for v in st.values())); orig = orig[:n]; st = {k: v[:n] for k, v in st.items()}
        bed = st["vocals"] + st["bass"] + st["drums"] + st["piano"] + st["other"]
        mix = orig + song * bed + vox * st["vocals"] - gtr * st["guitar"]
        # what the listener gets: singing vs guitar while singing (1 s windows), before and after
        def sing_vs_gtr(v, g):
            w = SR; m = len(v) // w
            V = np.sqrt((v[:m * w].reshape(m, w, -1) ** 2).mean(axis=(1, 2))); G = np.sqrt((g[:m * w].reshape(m, w, -1) ** 2).mean(axis=(1, 2)))
            s = V > np.percentile(V, 60)
            return float(np.median(_db(V[s], G[s]))) if m and V.max() > 1e-3 else None   # None = no singing heard in this take
        k_v, k_g = 1 + song + vox, 1 - gtr
        b, a = sing_vs_gtr(st["vocals"], st["guitar"]), sing_vs_gtr(st["vocals"] * k_v, st["guitar"] * k_g)
        rep = {"before": None if b is None else round(b, 1), "after": None if a is None else round(a, 1)}
        sf.write(os.path.join(tmp, "mix.wav"), mix, SR, subtype="FLOAT")
        _ff(os.path.join(tmp, "mix.wav"), os.path.join(tmp, "clean.wav"), CLEAN)
        x = sf.read(os.path.join(tmp, "clean.wav"), always_2d=True, dtype="float32")[0]
        a = _active(x); x = x * (10 ** (-16 / 20) / a if a > 0 else 1.0)
        sf.write(os.path.join(tmp, "lvl.wav"), x, SR, subtype="FLOAT")
        _ff(os.path.join(tmp, "lvl.wav"), os.path.join(tmp, "fin.wav"), "alimiter=limit=0.89:attack=5:release=80:level=false")
        y = sf.read(os.path.join(tmp, "fin.wav"), always_2d=True, dtype="float32")[0]
        rep["peak"] = round(float(20 * np.log10(np.abs(y).max() + 1e-9)), 1)
        sf.write(out_wav, y, SR, subtype="PCM_16")
        return rep
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def report_text(r):
    if r.get("before") is None:
        return f"🌿 Natural sound: song turned up, guitar a little down (no singing heard in this take) · peak {r['peak']:.1f} dBFS · no clipping"
    return f"🌿 Natural sound: singing {r['before']:+.1f} → {r['after']:+.1f} dB over your guitar · peak {r['peak']:.1f} dBFS · no clipping"


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    print(report_text(natural(sys.argv[1], sys.argv[2])))
