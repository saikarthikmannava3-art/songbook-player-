#!/usr/bin/env python3
"""check_timing.py — gate 9 (bar-line / timing filter) for every song.

Scores each chart version against the recording with the whole chart shifted by −3…+3 beats (quarter-beat steps).
If a shifted grid fits clearly better than the current one, the bar lines are wrong (e.g. the beat tracker picked
beat 2 as "1" — Nalone Pongenu was one beat late until 2026-11-12). Also reports where the bass hits hardest in
the bar: on a correct grid that is normally beat 1.

Usage:  ~/.venvs/demucs/bin/python pipeline/check_timing.py [song-id ...] [path/to/song.json ...]
Audio:  audio/<Title> - *.mp3|m4a (the original); if a "<…> stems" folder exists, the instruments
        (guitar+piano+bass+other, no vocals/drums) are used, which is much more reliable.
"""
import glob, json, os, sys
import numpy as np, librosa
sys.path.insert(0, os.path.dirname(__file__))
import songbook_pipeline as P  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SR, HOP = 22050, 512
BASS_RATIO = 2.5   # bass must hit that other beat this many times harder than "1" (Nalone's late grid: 5.9x; pushes in 7 Years: 2.2x)
FLAG_GAIN = 0.03   # the bass-suggested grid must fit the chords this much better (cosine) to flag


def find_audio(title):
    """Instrument stems for the song; separates the original with Demucs (cached in audio/stems/) if needed."""
    base = os.path.join(ROOT, "audio")
    stems = [d for d in glob.glob(os.path.join(base, glob.escape(title) + "*stems")) + glob.glob(os.path.join(base, "stems", "htdemucs_6s", glob.escape(title) + "*"))
             if os.path.isdir(d) and os.path.exists(os.path.join(d, "bass.wav"))]
    if stems:
        return stems[0], True
    files = [f for f in glob.glob(os.path.join(base, glob.escape(title) + " - *")) if f.endswith((".mp3", ".m4a")) and "backing" not in f]
    if not files:
        return None, False
    import subprocess
    print(f"   separating {os.path.basename(files[0])} with Demucs…", flush=True)
    r = subprocess.run([sys.executable, "-m", "demucs", "-n", "htdemucs_6s", "-o", os.path.join(base, "stems"), files[0]], capture_output=True)
    d = os.path.join(base, "stems", "htdemucs_6s", os.path.splitext(os.path.basename(files[0]))[0])
    return (d, True) if r.returncode == 0 and os.path.exists(os.path.join(d, "bass.wav")) else (files[0], False)


def load(path, is_stems):
    if is_stems:
        y = sum(librosa.load(os.path.join(path, s + ".wav"), sr=SR)[0] for s in ("guitar", "piano", "bass", "other"))
        bass = librosa.load(os.path.join(path, "bass.wav"), sr=SR)[0]
    else:
        y = librosa.load(path, sr=SR)[0]
        bass = None
    C = librosa.feature.chroma_cqt(y=y, sr=SR, hop_length=HOP, bins_per_octave=36)
    return C, librosa.frames_to_time(np.arange(C.shape[1]), sr=SR, hop_length=HOP), bass


def beats_of(song, ver):
    bp, bpb = 60 / song["bpm"], song.get("beatsPerBar", 4)
    out = []
    for sec, t0 in zip(song["versions"][ver]["sections"], song["map"]):
        k = 0
        for b in sec["bars"]:
            for c, d in P.parse_bar(b, bpb):
                for _ in range(int(round(d))):
                    out.append((t0 + k * bp, c, k % bpb)); k += 1
    return out


def fit(C, ft, beats, capo, bp, shift):
    T, s = {}, []
    for t, c, _ in beats:
        t += shift; m = (ft >= t) & (ft < t + bp)
        if not m.any(): continue
        v = C[:, m].mean(1); v = v - v.mean(); n = np.linalg.norm(v)
        if n < 1e-6: continue
        if c not in T: T[c] = P.chord_template(c, capo)
        s.append(T[c] @ (v / n))
    return float(np.mean(s)) if s else 0.0


def bass_by_beat(bass, beats, bpb):
    e = librosa.onset.onset_strength(y=bass, sr=SR, hop_length=256); et = librosa.frames_to_time(np.arange(len(e)), sr=SR, hop_length=256)
    acc, n = np.zeros(bpb), np.zeros(bpb)
    for t, _, p in beats:
        m = (et >= t - 0.05) & (et < t + 0.05)
        if m.any(): acc[p] += e[m].max(); n[p] += 1
    return acc / np.maximum(n, 1)


def check(song):
    path, is_stems = find_audio(song["title"])
    if not path:
        return {"id": song["id"], "status": "no audio"}
    C, ft, bass = load(path, is_stems)
    bp, bpb = 60 / song["bpm"], song.get("beatsPerBar", 4)
    ver = "intermediate" if "intermediate" in song["versions"] else next(iter(song["versions"]))
    beats = beats_of(song, ver)
    shifts = np.arange(-3, 3.01, 0.25)
    scores = {float(s): fit(C, ft, beats, song.get("capo", 0), bp, s * bp) for s in shifts}
    best = max(scores, key=scores.get)
    r = {"id": song["id"], "audio": os.path.basename(path) + (" (instruments)" if is_stems else " (full mix)"),
         "fit_now": round(scores[0.0], 3), "best_shift_beats": best, "fit_best": round(scores[best], 3)}
    if bass is not None:
        bb = bass_by_beat(bass, beats, bpb); r["bass_by_beat"] = [round(float(x), 2) for x in bb]; r["bass_peak_beat"] = int(np.argmax(bb)) + 1
    # Deciding test = the bass downbeat (chord fit alone leans early: pop harmony often changes just before the bar line).
    # Flag when the bass hits hardest on another beat AND moving the bar line to that beat also fits the chords better.
    if "bass_peak_beat" in r and r["bass_peak_beat"] != 1 and bb.max() >= BASS_RATIO * max(bb[0], 1e-6):
        k = r["bass_peak_beat"] - 1; alt = float(-(bpb - k) if k > bpb / 2 else k)   # nearest shift that puts that beat on "1"
        r["suggest_shift_beats"] = alt
        r["ok"] = not (scores.get(alt, 0) - scores[0.0] >= FLAG_GAIN)
    else:
        r["ok"] = True if "bass_peak_beat" in r else None   # None = unverified (no bass stem)
    return r


def main():
    args = sys.argv[1:]
    files = [a for a in args if a.endswith(".json")]          # check a specific JSON (e.g. an old revision)
    ids = {a for a in args if not a.endswith(".json")}
    bad = 0
    for f in files or sorted(glob.glob(os.path.join(ROOT, "songs", "*.json"))):
        for song in json.load(open(f)).get("songs", []):
            if ids and song["id"] not in ids: continue
            if "map" not in song or "versions" not in song: continue
            r = check(song)
            if r.get("status"):
                print(f"·  {song['id']:22s} {r['status']}"); continue
            bad += r["ok"] is False
            msg = (f"{'✓' if r['ok'] else ('?' if r['ok'] is None else '✗')}  {r['id']:22s} fit {r['fit_now']:.3f}; best shift {r['best_shift_beats']:+.2f} beats → {r['fit_best']:.3f}"
                   + (f"; bass hits hardest on beat {r['bass_peak_beat']} {r['bass_by_beat']}" if "bass_peak_beat" in r else "")
                   + (f"; → move bar lines {r['suggest_shift_beats']:+.0f} beat(s)" if r["ok"] is False else "") + f"  [{r['audio']}]")
            print(msg, flush=True)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
