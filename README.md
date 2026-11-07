# Songbook Player

Guitar play-along app: moving chord cards, strum patterns, metronome with a 3-2-1 count-in, a warm-up plan per song, lyrics with chords that light up, and chord charts timed to your own recording.

**Run it:** open **https://saikarthikmannava3-art.github.io/songbook-player-/** on any phone or computer (GitHub Pages, updates a minute after each push). On iPhone: Safari → Share → **Add to Home Screen** for a full-screen app. Or open `index.html` locally in Chrome.

**Run it with the extras (🎸 Remove guitar, auto-loaded lyrics/PDFs):**
```bash
~/.venvs/demucs/bin/python pipeline/serve.py      # then open http://localhost:8000/index.html
```
`serve.py` works like `python3 -m http.server 8000`, plus a local endpoint that makes no-guitar backing tracks.

## Features
- **Left panel** (🎸 My guitar): 🎚️ Tuner (YIN pitch detection, filters + adaptive noise gate, alternate tunings, A4 calibration, auto or locked string, mic picker, ✓ per string), 🎓 Guitar course, 🎵 Songs.
- **Right panel** (🎤 Live): current chord with shape and beat countdown, next chord changes, and lyrics that scroll with the song and highlight only the words of the current chord.
- **Song header** with artist photos (tap a photo to use your own), capo/key/tempo, chord version and strumming (chords shown in their lane colours).
- **🎓 Guitar course** side panel: JustinGuitar Grade 1 (Modules 0–7) and Grade 2 (Module 8) from Karthik Songbook pages 4–11, with module/lesson ticks, the Grade 1 checklist, strumming order, a 20-minute session and *My 5 songs*. Progress is kept in the browser (included in ⚙︎ Backup).
- **🎸 Song practice**: Play along on YouTube, 📄 Song sheet (the song's page from your songbook PDF), chord shapes & tips, warm-up plan, chord & strumming drill with a moving strum marker, one-minute chord changes.
- **Song map**, sticky **player** (Practice / YouTube / your file), moving **chord lane** with section headings on the left, **lyrics with chords** that follow the song (collapsible).
- **📚 Songbook**: upload PDFs (kept in the browser), ★ link a page to a song; books listed in `songbook/songbook.json` load automatically.
- **🎸 Remove guitar**: turns the song's MP3 into a play-along backing (needs `serve.py`).

## Make a no-guitar backing track
```bash
brew install ffmpeg python@3.12
python3.12 -m venv ~/.venvs/demucs && ~/.venvs/demucs/bin/pip install demucs soundfile "numpy<2"
~/.venvs/demucs/bin/python pipeline/make_backing.py "Song.mp3" --title "Song" --artist "Artist"
```
Demucs splits the song into 6 stems; the guitar is removed, everything else stays, and a soft guide guitar fills only the parts where the band drops out (intros, breaks). Output goes to `~/Downloads/Songbook Backing Tracks/` named so **📁 Connect my music folder** matches it to the song. `--guide 0` = no guitar at all.

## What's in here
| Path | What it is |
|---|---|
| `index.html` | The whole app (no song audio or lyrics inside) |
| `template.html` | The app source; `/*SONGS*/[]` is replaced with the song list at build time |
| `songs/*.json` | One song per file (open with **⇧ Open song file**) |
| `pipeline/songbook_pipeline.py` | Times a song chart to an MP3/M4A (gates 4–6 of the 7-gate checklist) |
| `pipeline/make_backing.py` | Makes a no-guitar play-along backing from a song file (Demucs) |
| `pipeline/serve.py` | Local server for the app + the 🎸 Remove guitar button |
| `images/artists/` | Artist photos from Wikimedia Commons — authors and licences in `CREDITS.json` |

## Your own files (not in the repo)
Song MP3s and lyrics `.txt` files are copyrighted, so `.gitignore` keeps them out. The same goes for `audio/` (backing tracks, stems), `songs/<id>-lyrics.txt` (lyrics the app loads automatically when present) and `songbook/` (your songbook PDFs and their page index). Load them in the app with **🎵 Load song file** / **📁 Connect my music folder** and **⇧ Open .txt** — the app remembers them on each device.

## Mandatory song pipeline
1. Sources (≥2) · 2. Key/capo/tempo verified · 3. Chords cross-checked · 4. Beats from the recording · 5. Sections aligned · 6. Measured accuracy ≥ 80% · 7. Lyrics match the chart.
Songs that miss a gate show as **Draft** in the app.

```bash
pip install librosa numpy        # plus ffmpeg for mp3/m4a
python3 pipeline/songbook_pipeline.py songs/7-years.json "7 Years.m4a" --out songs/7-years.json
```
