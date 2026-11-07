#!/usr/bin/env python3
"""
make_backing.py: turn a song (MP3/M4A/WAV…) into a guitar play-along backing track.

What it does (same recipe as the 7 Years and Parvati backings):
  1. Splits the song into 6 stems with Demucs (htdemucs_6s): vocals, drums, bass, guitar, piano, other.
  2. Rebuilds the mix WITHOUT the guitar: vocals + drums + bass + piano + other at full level.
  3. Where the accompaniment drops out (drums + bass + piano + other all quiet: guitar-only intros,
     breaks, endings), it brings back a soft guide guitar (default 50 %) with ~1 s fades, so those
     parts don't go silent or bare. Piano/keys intros stay as they are. Guitar-and-voice songs with
     no band at all get the guide guitar at 35 % throughout.
  4. Writes an AAC .m4a named "<Title> - <Artist> (backing, no guitar, soft guitar intro).m4a"
     (the player's 📁 Connect my music folder matches it to the song by that name).

Needs: ffmpeg, plus Python with demucs + soundfile + numpy, e.g.
  brew install ffmpeg python@3.12
  python3.12 -m venv ~/.venvs/demucs && ~/.venvs/demucs/bin/pip install demucs soundfile "numpy<2"

Use:
  ~/.venvs/demucs/bin/python pipeline/make_backing.py "~/Downloads/Song.mp3" --title "Song" --artist "Artist"
  ~/.venvs/demucs/bin/python pipeline/make_backing.py ~/Music/*.mp3            # several at once
Options: -o OUTDIR (default ~/Downloads/Songbook Backing Tracks) · --guide 0.5 (0 = no guitar at all)
         --keep-stems (leave the split stems next to the output)
Audio stays on your computer; nothing is uploaded.
"""
import argparse, json, os, re, shutil, subprocess, sys, tempfile

DEFAULT_OUT = os.path.expanduser("~/Downloads/Songbook Backing Tracks")
MODEL = "htdemucs_6s"


def _need(mod):
    try:
        return __import__(mod)
    except ImportError:
        sys.exit(f"Missing Python package '{mod}'. Run this script with the Demucs venv, e.g. ~/.venvs/demucs/bin/python")


def clean_name(s):
    return re.sub(r'[\\/:*?"<>|]+', " ", s).strip()


def out_name(src, title=None, artist=None, guide=0.5):
    base = " - ".join(x for x in [title, artist] if x) or os.path.splitext(os.path.basename(src))[0]
    tag = "backing, no guitar, soft guitar intro" if guide > 0 else "backing, no guitar"
    return clean_name(f"{base} ({tag})") + ".m4a"


def separate(src, work):
    """Run Demucs; returns the folder holding the 6 stem wavs."""
    cmd = [sys.executable, "-m", "demucs", "-n", MODEL, "-o", work, src]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit("Demucs failed:\n" + (r.stderr or r.stdout)[-2000:])
    d = os.path.join(work, MODEL, os.path.splitext(os.path.basename(src))[0])
    if not os.path.isdir(d):
        sys.exit("Demucs finished but its stems weren't found in " + work)
    return d


def guide_gain(accomp, sr, guide):
    """Per-sample guitar gain: `guide` where the accompaniment (drums+bass+piano+other) is bare, 0 elsewhere.
    Bare = quieter than -45 dBFS or 20 dB under the song's typical accompaniment level, held >= ~1.5 s, ~1 s fades.
    Songs with almost no accompaniment at all (guitar + voice) get a lower guide level so the backing isn't just vocals."""
    np = _need("numpy")
    hop = sr // 4                                   # 0.25 s steps, 1 s RMS window
    a = accomp.mean(1) if accomp.ndim > 1 else accomp
    rms = np.array([np.sqrt(np.mean(a[i:i + sr] ** 2)) for i in range(0, len(a), hop)])
    db = 20 * np.log10(rms + 1e-9)
    typical = float(np.percentile(db, 75))
    sparse = ((db < -45) | (db < typical - 20)).astype(float)
    k = 6                                           # ignore gaps shorter than ~1.5 s
    sp = np.array([sparse[max(0, i - k // 2):i + k // 2 + 1].min() for i in range(len(sparse))])
    frac = float(sp.mean())
    level = guide if frac < 0.6 else min(guide, 0.35)
    g = sp * level
    ker = np.ones(4) / 4
    g = np.convolve(np.convolve(g, ker, "same"), ker, "same")
    segs, st = [], None
    for i, v in enumerate(g > 0.05):
        if v and st is None: st = i
        if not v and st is not None: segs.append((st * 0.25, i * 0.25)); st = None
    if st is not None: segs.append((st * 0.25, len(g) * 0.25))
    return np.interp(np.arange(len(a)), np.arange(len(g)) * hop, g), segs, frac, level


def make_backing(src, outdir=DEFAULT_OUT, title=None, artist=None, guide=0.5, keep_stems=False, log=print):
    np, sf = _need("numpy"), _need("soundfile")
    if not shutil.which("ffmpeg"):
        sys.exit("ffmpeg not found (brew install ffmpeg)")
    src = os.path.abspath(os.path.expanduser(src))
    os.makedirs(outdir, exist_ok=True)
    work = tempfile.mkdtemp(prefix="sb-backing-")
    try:
        log(f"Splitting {os.path.basename(src)} into stems (a minute or two)…")
        d = separate(src, work)
        S = {n: sf.read(os.path.join(d, n + ".wav"))[0] for n in ["vocals", "drums", "bass", "guitar", "piano", "other"]}
        sr = sf.info(os.path.join(d, "drums.wav")).samplerate
        g, segs, frac, level = guide_gain(S["drums"] + S["bass"] + S["piano"] + S["other"], sr, guide)
        mix = S["vocals"] + S["drums"] + S["bass"] + S["piano"] + S["other"] + S["guitar"] * g[:, None]
        pk = float(np.abs(mix).max())
        if pk > 0.95: mix = mix / pk * 0.95
        wav = os.path.join(work, "mix.wav")
        sf.write(wav, mix, sr)
        out = os.path.join(outdir, out_name(src, title, artist, guide))
        r = subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", wav, "-c:a", "aac", "-b:a", "192k", out], capture_output=True, text=True)
        if r.returncode != 0:
            sys.exit("ffmpeg failed: " + r.stderr[-1000:])
        if keep_stems:
            shutil.copytree(d, os.path.splitext(out)[0] + " stems", dirs_exist_ok=True)
        fmt = lambda t: f"{int(t // 60)}:{t % 60:04.1f}"
        info = {"output": out, "duration": round(len(mix) / sr, 2), "guide": level, "bare_fraction": round(frac, 2),
                "acoustic": frac >= 0.6,
                "guide_guitar_at": [[fmt(a), fmt(b)] for a, b in segs] if guide > 0 else []}
        log(f"✓ {os.path.basename(out)}" + (f" · soft guitar at {', '.join(a + '–' + b for a, b in info['guide_guitar_at'])}" if info["guide_guitar_at"] else ""))
        return info
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser(description="Make a no-guitar play-along backing track from a song file.")
    ap.add_argument("inputs", nargs="+", help="MP3/M4A/WAV files")
    ap.add_argument("-o", "--outdir", default=DEFAULT_OUT)
    ap.add_argument("--title"); ap.add_argument("--artist")
    ap.add_argument("--guide", type=float, default=0.5, help="guide-guitar level where the band drops out (0 = none)")
    ap.add_argument("--keep-stems", action="store_true")
    a = ap.parse_args()
    if len(a.inputs) > 1 and (a.title or a.artist):
        sys.exit("--title/--artist only work with a single input file")
    res = [make_backing(f, a.outdir, a.title, a.artist, a.guide, a.keep_stems) for f in a.inputs]
    print(json.dumps(res, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
