#!/usr/bin/env python3
"""
Songbook song pipeline — MANDATORY for every song added to Songbook Player.

Every song goes through all 7 gates below. A song file is only "release" quality
when its `qa` block shows every gate passed. Gates 1–3 are research (done by Claude
with web sources); gates 4–7 are run by this script against the user's own audio file.

  GATE 1  SOURCES      ≥2 independent chord sources (e.g. Ultimate Guitar + Cifra Club / Chordify)
                       plus the user's sheet if given. Record every URL in song["sources"].
  GATE 2  KEY/TEMPO    Key, capo and BPM confirmed by an authoritative source
                       (Wikipedia / Musicnotes official sheet / Songbpm) — never guessed.
  GATE 3  CHORDS &     Research the song's tutorials / chord sites first. Easy, Medium and Hard chord versions
          STRUMMING    and every strumming pattern come ONLY from those sources, the user, or a measurement of
                       the recording — never a generic default (e.g. "D DU UDU"). Each version and each strum
                       carries "src": {"label", "url"}. Disagreements: the recording decides; list them in
                       qa["disputed"]. Easy = open chords only (barre → open shape: F→Fmaj7, Bm→Bm7 …).
                       check_rules() below enforces this; any problem sets qa["g3"] = false.
  GATE 4  BEATS        Beat-track the recording; tempo from the AVERAGE beat interval
                       (the median is quantised by the analysis hop and can be off by 2–3 BPM).
  GATE 5  ALIGN        Align the chart's chord changes to beat-synchronous chroma
                       (harmonic part only, capo transposition applied) with a left-to-right HMM;
                       derive the first downbeat, every section start (→ song["map"]) and
                       section lengths. Fix the chart's bar counts to what the audio shows.
  GATE 6  SCORE        Measure the share of beats where the chart chord is the best-matching
                       chord in the audio. Release threshold: ≥80% top-1 (≥85% top-2).
                       Never state a confidence that was not measured.
  GATE 7  LYRICS       Lyrics-with-chords (.txt, [Chord]word) must match the chart section by
                       section (same chord-change order). The app re-checks this when it loads
                       the .txt; any mismatch blocks the "lyrics follow live" feature.

After release: the user's ✋ taps (saved anchors) are the final authority and override the
measured timing for the changes they tapped. Bump song["rev"] on every re-release so stale
per-device settings (old BPM / sync) are discarded automatically.

Usage:
  python3 songbook_pipeline.py SONG.json AUDIO.(mp3|m4a|wav) [--out SONG_fitted.json] [--chroma-audio HARMONY.wav]
  (HARMONY.wav = the song without vocals and drums, e.g. from Demucs stems — chords are then scored on what the
   instruments play, not on the sung melody. make_backing.py --keep-stems gives you the stems.)
Needs: librosa, numpy (pip install librosa), ffmpeg for m4a/mp3.
"""
import sys, json, argparse, subprocess, tempfile, os
import numpy as np

NOTE = {'C':0,'C#':1,'Db':1,'D':2,'D#':3,'Eb':3,'E':4,'F':5,'F#':6,'Gb':6,'G':7,'G#':8,'Ab':8,'A':9,'A#':10,'Bb':10,'B':11}
RELEASE_TOP1, RELEASE_TOP2 = 0.80, 0.85

def chord_template(name, capo):
    main, _, bass = name.partition('/')
    root = main[:2] if len(main) > 1 and main[1] in '#b' else main[:1]
    q = main[len(root):]; r = NOTE[root]
    iv = [0,3,7] if (q.startswith('m') and not q.startswith('maj')) else [0,4,7]
    if 'dim' in q: iv = [0,3,6]
    if 'sus2' in q: iv = [0,2,7]
    if 'sus4' in q or q == 'sus': iv = [0,5,7]
    if 'maj7' in q: iv.append(11)
    elif '7' in q: iv.append(10)
    if 'add9' in q: iv.append(2)
    v = np.zeros(12)
    for i in iv: v[(r+i+capo) % 12] = 1
    v[(r+capo) % 12] = 1.4
    if bass:
        b = bass[:2] if len(bass) > 1 and bass[1] in '#b' else bass[:1]
        v[(NOTE[b]+capo) % 12] += 0.6
    v = v - v.mean(); return v / np.linalg.norm(v)

def parse_bar(bar, bpb):
    toks = []
    for t in bar.split():
        c, _, d = t.partition(':'); toks.append([c, float(d) if d else None])
    fixed = sum(d for _, d in toks if d); free = [t for t in toks if t[1] is None]
    for t in free: t[1] = (bpb - fixed) / max(len(free), 1)
    return toks

OPEN_CHORDS = {"A","Am","A7","Am7","Asus2","Asus4","Aadd9","B7","Bm7","C","C7","Cadd9","Cmaj7","Csus2","D","D7","Dm","Dm7",
               "Dmaj7","Dsus2","Dsus4","D/F#","E","E7","Em","Em7","Esus4","Emaj7","Fmaj7","G","G7","Gmaj7","Gsus2","Gsus4",
               "G/B","Em/G","C/G"}

def check_rules(song):
    """Gate 3 rules — same checks as ruleIssues() in index.html."""
    out = []
    for i, s in enumerate(song.get('strums', [])):
        if not s.get('src'): out.append(f"Pattern {i+1} ({s.get('label', s.get('s'))[:40]}) has no source")
    for k, n in (('simple', 'Easy'), ('intermediate', 'Medium'), ('band', 'Hard')):
        v = song.get('versions', {}).get(k)
        if v is not None and not v.get('src'): out.append(f"{v.get('label', n)} chords have no source")
    e = song.get('versions', {}).get('simple')
    if e:
        bad = sorted({t.split(':')[0] for sec in e['sections'] for b in sec['bars'] for t in b.split()} - OPEN_CHORDS)
        if bad: out.append('Easy uses barre chords: ' + ', '.join(bad))
    return out

def load_audio(path, sr=22050):
    import librosa
    if not path.lower().endswith('.wav'):
        tmp = tempfile.mktemp(suffix='.wav')
        subprocess.run(['ffmpeg','-loglevel','error','-y','-i',path,'-ac','1','-ar',str(sr),tmp], check=True)
        path = tmp
    y, _ = librosa.load(path, sr=sr); return y, sr

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('song'); ap.add_argument('audio'); ap.add_argument('--out')
    ap.add_argument('--chroma-audio', help='harmony-only audio for gates 5-6 (e.g. guitar+piano+other+bass stems, no vocals/drums); beats still come from AUDIO')
    a = ap.parse_args()
    import librosa
    doc = json.load(open(a.song)); song = doc['songs'][0] if 'songs' in doc else doc
    bpb = song.get('beatsPerBar', 4); capo = int(song.get('capo') or 0)
    secs = song['versions']['intermediate']['sections']

    # GATE 4 — beats
    y, sr = load_audio(a.audio)
    _, beats = librosa.beat.beat_track(y=y, sr=sr, start_bpm=song.get('bpm', 120), tightness=200, units='frames')
    bt = librosa.frames_to_time(beats, sr=sr)
    bpm = 60.0 / float(np.mean(np.diff(bt)))
    yh = load_audio(a.chroma_audio, sr)[0] if a.chroma_audio else librosa.effects.harmonic(y)   # sung melody notes skew chord chroma
    if len(yh) < len(y): yh = np.pad(yh, (0, len(y) - len(yh)))
    C = librosa.util.sync(librosa.feature.chroma_cqt(y=yh[:len(y)], sr=sr, bins_per_octave=36), beats, aggregate=np.median)
    NB = min(C.shape[1], len(bt)); C = C[:, :NB]
    X = C - C.mean(axis=0, keepdims=True); X /= np.linalg.norm(X, axis=0, keepdims=True) + 1e-9

    # GATE 5 — HMM alignment of chord-change states (min 2 beats each)
    states = []
    for si, s in enumerate(secs):
        prev = None
        for b in s['bars']:
            for c, _ in parse_bar(b, bpb):
                if c != prev: states.append((si, c)); prev = c
    E = np.array([chord_template(c, capo) @ X for _, c in states]) * 6.0
    S = len(states); SS = 2 * S; L = np.repeat(E, 2, axis=0)
    NEG = -1e18; D = np.full((SS, NB), NEG); B = np.zeros((SS, NB), dtype=int); D[0, 0] = L[0, 0]
    stay, adv = np.log(0.8), np.log(0.2)
    for t in range(1, NB):
        p = D[:, t-1]; cs = np.full(SS, NEG); ca = np.full(SS, NEG)
        cs[1::2] = p[1::2] + stay; ca[2::2] = p[1:-1:2] + adv; ca[1::2] = np.maximum(ca[1::2], p[0::2])
        bet = ca > cs; D[:, t] = np.where(bet, ca, cs) + L[:, t]; B[:, t] = np.where(bet, np.arange(SS)-1, np.arange(SS))
    s = SS - 1; path = [s]
    for t in range(NB-1, 0, -1): s = B[s, t]; path.append(s)
    path = np.array(path[::-1]) // 2
    starts = [int(np.argmax(path == k)) if (path == k).any() else None for k in range(S)]
    # downbeat phase = phase most chord changes fall on
    ch = [x for x in starts if x is not None]
    phase = max(range(bpb), key=lambda p: sum((x - p) % bpb == 0 for x in ch))
    sec_beats = []
    for si in range(len(secs)):
        k = next(i for i, (q, _) in enumerate(states) if q == si)
        b0 = starts[k]; dn = b0 - ((b0 - phase) % bpb)            # snap to the nearest downbeat
        sec_beats.append(dn if b0 - dn <= bpb / 2 else dn + bpb)
    # grid refinement: if the chart's bar counts explain most section starts, trust the grid
    cum = np.cumsum([0] + [len(s['bars']) for s in secs])[:-1] * bpb
    g0 = int(np.median(np.array(sec_beats) - cum)); g0 -= (g0 - phase) % bpb
    fits = [abs(sb - (g0 + c)) <= bpb for sb, c in zip(sec_beats, cum)]
    overridden = []
    if sum(fits) >= 0.7 * len(secs):
        # the chart's bar counts explain most of the song: trust the grid everywhere. Sections that
        # disagree are usually long one-chord stretches where the chroma can't see a boundary.
        for i, (sb, c) in enumerate(zip(sec_beats, cum)):
            if abs(sb - (g0 + c)) > bpb: overridden.append(secs[i]['name'])
        sec_beats = [int(g0 + c) for c in cum]
    sec_beats = [max(0, min(NB - 1, b)) for b in sec_beats]
    sec_map = [round(float(bt[b]), 3) for b in sec_beats]
    lengths = [(sec_beats[i+1] - sec_beats[i]) // bpb if i+1 < len(sec_beats) else None for i in range(len(sec_beats))]

    # GATE 6 — score
    names = sorted({c for _, c in states}); T = {n: chord_template(n, capo) for n in names}
    top1 = top2 = tot = 0
    for si, s in enumerate(secs):
        beat = sec_beats[si]
        for b in s['bars']:
            at = 0
            for c, d in parse_bar(b, bpb):
                lo, hi = int(beat + at), int(beat + at + d); at += d
                if hi > NB or hi <= lo: continue
                v = C[:, lo:hi].mean(axis=1); v = v - v.mean(); v /= np.linalg.norm(v) + 1e-9
                rk = sorted(names, key=lambda n: -(T[n] @ v)); w = hi - lo
                tot += w; top1 += w * (rk[0] == c); top2 += w * (c in rk[:2])
            beat += bpb
    acc1, acc2 = (top1 / tot if tot else 0), (top2 / tot if tot else 0)

    rules = check_rules(song)
    report = {'rules_ok': not rules, 'rules_issues': rules, 'bpm_measured': round(bpm, 2), 'first_downbeat_s': sec_map[0] if sec_map else None,
              'section_starts_s': sec_map, 'section_bars_in_audio': lengths,
              'chart_bars': [len(s['bars']) for s in secs], 'top1': round(acc1, 3), 'top2': round(acc2, 3),
              'release_ok': acc1 >= RELEASE_TOP1 and acc2 >= RELEASE_TOP2, 'grid_overrode': overridden}
    print(json.dumps(report, indent=1))
    mism = [(s['name'], len(s['bars']), n) for s, n in zip(secs, lengths) if n is not None and n != len(s['bars'])]
    if mism: print('FIX BAR COUNTS (section, chart, audio):', mism)
    if a.out:
        song['map'] = sec_map; song['firstBeat'] = sec_map[0]; song['rev'] = int(song.get('rev', 0)) + 1
        qa = song.setdefault('qa', {}); qa.update({'gate4_bpm': report['bpm_measured'], 'gate5_map': True,
            'gate6_top1': report['top1'], 'gate6_top2': report['top2'], 'release_ok': report['release_ok']})
        if rules: qa['g3'] = False
        json.dump({'songbook': 1, 'songs': [song]}, open(a.out, 'w'), ensure_ascii=False, indent=1)
        print('wrote', a.out)

if __name__ == '__main__':
    main()
