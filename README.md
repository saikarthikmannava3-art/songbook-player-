# Songbook Player

Guitar play-along app: moving chord cards, strum patterns, metronome with a 3-2-1 count-in, a warm-up plan per song, lyrics with chords that light up, and chord charts timed to your own recording.

**Run it:** open `index.html` in Chrome — or turn on GitHub Pages (Settings → Pages → Deploy from branch → `main` / root) and open the page on any phone or computer.

## What's in here
| Path | What it is |
|---|---|
| `index.html` | The whole app (no song audio or lyrics inside) |
| `template.html` | The app source; `/*SONGS*/[]` is replaced with the song list at build time |
| `songs/*.json` | One song per file (open with **⇧ Open song file**) |
| `pipeline/songbook_pipeline.py` | Times a song chart to an MP3/M4A (gates 4–6 of the 7-gate checklist) |

## Your own files (not in the repo)
Song MP3s and lyrics `.txt` files are copyrighted, so `.gitignore` keeps them out. Load them in the app with **🎵 Load song file** / **📁 Connect my music folder** and **⇧ Open .txt** — the app remembers them on each device.

## Mandatory song pipeline
1. Sources (≥2) · 2. Key/capo/tempo verified · 3. Chords cross-checked · 4. Beats from the recording · 5. Sections aligned · 6. Measured accuracy ≥ 80% · 7. Lyrics match the chart.
Songs that miss a gate show as **Draft** in the app.

```bash
pip install librosa numpy        # plus ffmpeg for mp3/m4a
python3 pipeline/songbook_pipeline.py songs/7-years.json "7 Years.m4a" --out songs/7-years.json
```
