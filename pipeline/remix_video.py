#!/usr/bin/env python3
"""remix_video.py — give an existing Songbook video a better sound, keeping its picture (lyrics/chords already drawn in).

Default — 🌿 natural (the app's default too): your phone's own recording, rebalanced with its own Demucs stems:
song + singing up, guitar a little down, light clean-up, −16 dB level, −1 dBFS limiter (pipeline/natural_mix.py).
Nothing is layered on top, so it sounds like the room, not "separated". Chosen on Nenu Nuvvantu (version C).

  ~/.venvs/demucs/bin/python pipeline/remix_video.py LYRICS_VIDEO.mp4 RECORDING.mov

--separated: the older method, = the app with 🌿 off (index.html: guitarChain → videoMix):
  1. Your guitar: Demucs pulls it out of your phone recording (the room's copy of the song is dropped),
     plus a 5 % trace of the room so it still sounds live; the app's guitar tone (no pick/air boost, cut at 4.2 kHz).
  2. The song: the no-guitar backing (best), or --song-from VIDEO: the song recovered from an older render of this
     take (everything except the guitar) when no song file is around.
  3. Lines the song up with your recording (the room's song vs the song file), then videoMix from index.html via node:
     strum spikes held to 12 dB, guitar 6 dB (--gdb) under the song, −16 dB level, −1 dBFS look-ahead limiter.
  4. Prints the sound check and writes "<video> (NEW sound).mp4" next to the video.

Usage:
  ~/.venvs/demucs/bin/python pipeline/remix_video.py LYRICS_VIDEO.mp4 RECORDING.mov --separated --song BACKING.m4a [--gdb -4]
  ~/.venvs/demucs/bin/python pipeline/remix_video.py LYRICS_VIDEO.mp4 RECORDING.mov --separated --song-from OLD_RENDER.mp4
Needs: ffmpeg, node, the Demucs venv (demucs, soundfile, numpy).
"""
import argparse, os, shutil, subprocess, sys, tempfile
import numpy as np, soundfile as sf
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import natural_mix

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SR = 44100
EQ = ("highpass=f=80,equalizer=f=220:t=q:w=1.2:g=-3,equalizer=f=800:t=q:w=0.8:g=-1,"          # = guitarChain() in index.html
      "equalizer=f=4200:t=q:w=1.1:g=-2.5,highshelf=f=9000:g=-1.5,acompressor=threshold=0.063:ratio=3:attack=3:release=150:knee=3")
NODE_MIX = r"""
const fs=require("fs");const h=fs.readFileSync(process.argv[2],"utf8");
const a=h.indexOf("const VMIX="),b=h.indexOf("function bufChs(");if(a<0||b<0)throw new Error("videoMix not found in index.html");
const f=new Function(h.slice(a,b)+";return {videoMix,soundReport};")();
const n=+process.argv[4],gdb=+process.argv[5],d=process.argv[3];
const rd=p=>{const x=new Float32Array(fs.readFileSync(p).buffer.slice(0));return [x.slice(0,n),x.slice(n,2*n)];};
const r=f.videoMix(rd(d+"/g.f32"),rd(d+"/b.f32"),44100,{gdb});
const o=new Float32Array(2*n);o.set(r.chs[0],0);o.set(r.chs[1],n);fs.writeFileSync(d+"/mix.f32",Buffer.from(o.buffer));
console.log(f.soundReport(r.report));
"""


def run(cmd, **k):
    p = subprocess.run(cmd, capture_output=True, text=True, **k)
    if p.returncode:
        sys.exit(f"✗ {' '.join(map(str, cmd[:3]))}…: {p.stderr[-500:]}")
    return p


def wav(src, dst, af=None):
    run(["ffmpeg", "-loglevel", "error", "-y", "-i", src, "-vn", "-ac", "2", "-ar", str(SR)] + (["-af", af] if af else []) + ["-c:a", "pcm_f32le", dst])
    return sf.read(dst, always_2d=True, dtype="float32")[0]


def split_guitar(src, tmp):
    """Demucs (two stems): returns (guitar, everything-else)."""
    run([sys.executable, "-m", "demucs", "-n", "htdemucs_6s", "--two-stems", "guitar", "-o", tmp, src])
    d = os.path.join(tmp, "htdemucs_6s", os.path.splitext(os.path.basename(src))[0])
    return [sf.read(os.path.join(d, n), always_2d=True, dtype="float32")[0] for n in ("guitar.wav", "no_guitar.wav")]


def onset_env(x, hop=441):
    m = x.mean(1); n = len(m) // hop
    e = np.sqrt((m[:n * hop].reshape(n, hop) ** 2).mean(1)); d = np.maximum(0, np.diff(np.log(e + 1e-6)))
    return (d - d.mean()) / (d.std() or 1)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("video"); ap.add_argument("recording")
    ap.add_argument("--separated", action="store_true", help="older method: separated guitar + a song file (needs --song or --song-from)")
    g = ap.add_mutually_exclusive_group(); g.add_argument("--song"); g.add_argument("--song-from")
    ap.add_argument("--gdb", type=float, default=-6, help="your guitar vs the song in dB (default −6)")
    ap.add_argument("--out")
    a = ap.parse_args()
    if a.separated and not (a.song or a.song_from): ap.error("--separated needs --song or --song-from")
    if not a.separated and (a.song or a.song_from): ap.error("--song/--song-from only apply with --separated")
    tmp = tempfile.mkdtemp(prefix="sb-remix-")
    try:
        if not a.separated:
            print("🌿 natural sound: rebalancing your recording with its own stems (Demucs, a few minutes)…")
            mixw = os.path.join(tmp, "mix.wav"); print("   " + natural_mix.report_text(natural_mix.natural(a.recording, mixw)))
            out = a.out or os.path.splitext(a.video)[0].replace(" (guitar fix + lyrics + backing)", "") + " (natural sound).mp4"
            run(["ffmpeg", "-loglevel", "error", "-y", "-i", a.video, "-i", mixw, "-map", "0:v:0", "-map", "1:a:0",
                 "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", out])
            print("✓ " + out); return
        print("1/4 separating your guitar from the recording (Demucs)…")
        rec = wav(a.recording, os.path.join(tmp, "rec.wav"))
        gtr, room_song = split_guitar(os.path.join(tmp, "rec.wav"), tmp)
        n = len(gtr)
        gtr = gtr + 0.05 * rec[:n]
        sf.write(os.path.join(tmp, "g_raw.wav"), gtr, SR, subtype="FLOAT")
        gtr = wav(os.path.join(tmp, "g_raw.wav"), os.path.join(tmp, "g_eq.wav"), EQ)[:n]
        print("2/4 the song…")
        if a.song:
            song = wav(a.song, os.path.join(tmp, "song.wav")); kind = "backing " + os.path.basename(a.song)
        else:
            old = wav(a.song_from, os.path.join(tmp, "old.wav"))
            _, song = split_guitar(os.path.join(tmp, "old.wav"), tmp); kind = "recovered from " + os.path.basename(a.song_from) + " (guitar taken out)"
        ev, es = onset_env(room_song[:n]), onset_env(song)
        c = np.correlate(es, ev, "full"); lag = int(np.argmax(c)) - (len(ev) - 1); score = c.max() / len(ev)
        st = lag * 441; seg = np.zeros((n, 2), np.float32); a0, w0 = max(0, st), max(0, -st); L = min(len(song) - a0, n - w0)
        if L > 0: seg[w0:w0 + L] = song[a0:a0 + L, :2]
        print(f"   song: {kind}; your recording starts at song time {st / SR:+.2f} s (match {score:.2f}{' ⚠ weak — check the result' if score < 0.1 else ''})")
        print("3/4 mixing (videoMix from index.html)…")
        np.ascontiguousarray(gtr[:, :2].T).tofile(os.path.join(tmp, "g.f32")); np.ascontiguousarray(seg.T).tofile(os.path.join(tmp, "b.f32"))
        js = os.path.join(tmp, "mix.js"); open(js, "w").write(NODE_MIX)
        p = run(["node", "--max-old-space-size=8000", js, os.path.join(ROOT, "index.html"), tmp, str(n), str(a.gdb)])
        print("   " + p.stdout.strip())
        mix = np.fromfile(os.path.join(tmp, "mix.f32"), np.float32).reshape(2, n).T
        sf.write(os.path.join(tmp, "mix.wav"), mix, SR, subtype="PCM_16")
        out = a.out or os.path.splitext(a.video)[0].replace(" (guitar fix + lyrics + backing)", "") + " (NEW sound).mp4"
        print("4/4 writing the video…")
        run(["ffmpeg", "-loglevel", "error", "-y", "-i", a.video, "-i", os.path.join(tmp, "mix.wav"), "-map", "0:v:0", "-map", "1:a:0",
             "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", out])
        print("✓ " + out)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
