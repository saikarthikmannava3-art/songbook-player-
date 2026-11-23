#!/usr/bin/env python3
"""fetch_lyrics.py — lyrics sheet for a song from its Ultimate Guitar page (gate 7).

Takes the words exactly as the Ultimate Guitar chart writes them and lays the song's own chart chords
(Easy version unless chosen otherwise) on top, so the sheet always passes gate 7 (same chord-change order as the chart):
  1. Fetches the UG chart (normal tab URL or the print/export URL with ?id=…).
  2. Splits it into blocks (blank lines / headings like "Charanam1:" or "[Chorus]"); drops chord-only lines,
     "Page 1/2" and one-line repeat markers such as "Nenu Nuvvantu(1)".
  3. Matches blocks to the chart's sections in order. A section whose name was seen before (Chorus 2,
     Pallavi 3 …) reuses that section's words, unless UG's next block has a heading of the same kind
     (Charanam2 after Charanam1). Intro / Instrumental / Interlude / Outro / Solo sections get chords only.
  4. Places the chart's chord changes on the words, preferring the spots where UG has the same chord
     (UG's key and capo are detected automatically — any transposition works).
  5. Writes songs/<id>-lyrics.txt (git-ignored: lyrics are copyrighted) and, if .songbook-key exists,
     saves it to the private cloud store (/api/lyrics) so linked devices get it.
The UG link is stored in the song as "lyricsSrc" (with the chord version and an "updated" stamp), so later runs
need only the song id; after a refresh, each device replaces its saved copy of the sheet once.

Usage:
  python3 pipeline/fetch_lyrics.py SONG_ID [UG_URL]      # first time: give the link; later: id only
  python3 pipeline/fetch_lyrics.py --all                 # refresh every song that has a lyricsSrc
Options: --no-cloud (don't upload) · --dry-run (print the sheet, write nothing) · --version simple|intermediate|band
         (chord version the sheet uses — saved in lyricsSrc.chords; default Easy, which fits playing along to a recording)
"""
import argparse, html, json, os, re, ssl, subprocess, sys, time, urllib.parse, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLOUD = "https://songbook-player.vercel.app/api/lyrics"
NOTE = {'C': 0, 'C#': 1, 'Db': 1, 'D': 2, 'D#': 3, 'Eb': 3, 'E': 4, 'F': 5, 'F#': 6, 'Gb': 6, 'G': 7, 'G#': 8, 'Ab': 8,
        'A': 9, 'A#': 10, 'Bb': 10, 'B': 11, 'H': 11}
INSTR = re.compile(r'intro|instrumental|interlude|outro|solo|break|ending riff|riff', re.I)


# ---------- fetching ----------
def http_get(url):
    hdr = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"}
    try:
        return urllib.request.urlopen(urllib.request.Request(url, headers=hdr), timeout=30).read().decode("utf-8", "replace")
    except (ssl.SSLError, urllib.error.URLError) as e:  # e.g. a TLS-inspecting proxy Python doesn't trust: curl uses the system store
        if "CERTIFICATE" not in str(e).upper() and not isinstance(e, ssl.SSLError):
            raise
        return subprocess.run(["curl", "-sL", "-A", hdr["User-Agent"], url], capture_output=True, text=True, check=True).stdout


def ug_url(url):
    """Print/export links (…/tab/print?id=123&…) → …/tab/print?id=123, which redirects to the normal tab page."""
    q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    if "/tab/print" in url and q.get("id"):
        return f"https://tabs.ultimate-guitar.com/tab/print?id={q['id'][0]}"
    return url


def fetch_ug(url):
    page = http_get(ug_url(url))
    m = re.search(r'class="js-store"\s+data-content="(.*?)"', page, re.S) or re.search(r'data-content="(.*?)"', page, re.S)
    if not m:
        sys.exit(f"Couldn't find the chart on {url} (Ultimate Guitar changed its page, or blocked the request).")
    data = json.loads(html.unescape(m.group(1)))["store"]["page"]["data"]
    tv, tab = data["tab_view"], data.get("tab", {})
    meta = tv.get("meta") if isinstance(tv.get("meta"), dict) else {}
    title = f'{tab.get("song_name", "")} — {tab.get("artist_name", "")}'.strip(" —")
    return tv["wiki_tab"]["content"], title


# ---------- chords ----------
def parse_chord(name):
    """'G#m7' → (8, 'm'); quality is only major / minor / dim for matching."""
    m = re.match(r'^([A-H][#b]?)(.*)$', name.strip())
    if not m or m.group(1) not in NOTE:
        return None
    q = m.group(2).split('/')[0]
    qual = 'dim' if 'dim' in q else ('m' if q.startswith('m') and not q.startswith('maj') else '')
    return NOTE[m.group(1)], qual


def same(a, b, shift):
    pa, pb = parse_chord(a), parse_chord(b)
    return bool(pa and pb and (pa[0] + shift) % 12 == pb[0] and pa[1] == pb[1])


# ---------- UG text → blocks ----------
CH = re.compile(r'\[ch\](.*?)\[/ch\]')


def ug_blocks(content):
    lines = content.replace('\r', '').replace('[tab]', '').replace('[/tab]', '').split('\n')
    blocks, cur, pending, heading = [], [], None, None

    def flush():
        nonlocal cur, heading
        if cur:   # (a blank line right after a heading keeps the heading for the next block)
            blocks.append({"heading": heading, "lines": cur})
            cur, heading = [], None

    for raw in lines:
        plain = CH.sub(lambda m: m.group(1), raw)
        if not plain.strip():
            if pending is None:
                flush()
            continue
        if re.match(r'^\s*page\s+\d+\s*/\s*\d+\s*$', plain, re.I) or re.match(r'^\s*https?://', plain):
            continue
        chords = []  # chord line: only chords left once the [ch] tags are removed
        if CH.search(raw) and not CH.sub('', raw).strip(' |-x0123456789()/.'):
            col = 0
            for part in re.split(r'(\[ch\].*?\[/ch\])', raw):
                m = CH.match(part)
                if m:
                    chords.append((col, m.group(1))); col += len(m.group(1))
                else:
                    col += len(part)
            if pending is not None:
                pass  # previous chord line had no lyric under it (instrumental line): dropped
            pending = chords
            continue
        hm = re.match(r'^\s*\[?([A-Za-z][A-Za-z \-]*?)\s*\d*\]?\s*:?\s*$', plain)
        if hm and (plain.strip().endswith(':') or plain.strip().startswith('[')) and len(plain.split()) <= 3:
            flush(); heading = hm.group(1).strip(); pending = None
            continue
        words = plain.rstrip(); lead = len(words) - len(words.lstrip()); words = words.lstrip()
        anchors = [(max(0, min(c - lead, len(words))), n) for c, n in (pending or [])]
        cur.append({"text": words, "anchors": anchors})
        pending = None
    flush()
    # under a heading ([Verse 1], Charanam1:) everything up to the next heading is one block (UG often puts blank
    # lines between the lines of a verse); chord-less text before the first heading is the uploader's preamble
    if any(b["heading"] for b in blocks):
        merged, seen_head = [], False
        for b in blocks:
            if b["heading"]:
                seen_head = True; merged.append({"heading": b["heading"], "lines": list(b["lines"])})
            elif seen_head:
                merged[-1]["lines"] += b["lines"]
            elif any(ln["anchors"] for ln in b["lines"]):
                merged.append(b)
        blocks = merged
    # drop one-line repeat markers ("Nenu Nuvvantu(1)", "Chorus x2") that echo an earlier block's opening
    norm = lambda s: re.findall(r'[a-z]+', s.lower())
    out = []
    for b in blocks:
        openings = [norm(o["lines"][0]["text"]) for o in out]
        def marker(ln):
            w = norm(ln["text"])
            return 0 < len(w) <= 4 and any(o[:len(w)] == w for o in openings)
        b = dict(b, lines=[ln for i, ln in enumerate(b["lines"]) if i == 0 or not marker(ln)])
        if len(b["lines"]) == 1 and len(norm(b["lines"][0]["text"])) <= 4 and out:
            w = norm(b["lines"][0]["text"])
            if any(norm(o["lines"][0]["text"])[:len(w)] == w for o in out) or re.search(r'chorus|repeat|x\s*\d', b["lines"][0]["text"], re.I):
                continue
        out.append(b)
    return out


# ---------- matching ----------
def base(name):
    s = re.sub(r'[—–-].*$', '', name.lower())
    return re.sub(r'[^a-z ]', '', s).strip()


def changes(section):
    out, prev = [], None
    for bar in section["bars"]:
        for t in str(bar).split():
            c = t.split(':')[0]
            if c and c != prev:
                out.append(c); prev = c
    return out


def ug_seq(blocks):
    s, prev = [], None
    for b in blocks:
        for ln in b["lines"]:
            for _, n in ln["anchors"]:
                if n != prev:
                    s.append(n); prev = n
    return s


def lcs(a, b, shift):
    D = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i in range(len(a)):
        for j in range(len(b)):
            D[i + 1][j + 1] = D[i][j] + 1 if same(a[i], b[j], shift) else max(D[i][j + 1], D[i + 1][j])
    return D[-1][-1]


def sim(blocks, ch, shift):
    u = ug_seq(blocks)
    if not u or not ch:
        return 0.0
    k = lcs(u, ch, shift); r, p = k / len(ch), k / len(u)
    # F2: covering the chart's changes matters more than UG's extra passing chords (G# before every Fm …)
    return 0 if k == 0 else 5 * r * p / (4 * p + r)


def detect_shift(blocks, sections):
    """Semitones from UG's chord names to the chart's names (UG may be in another key / capo)."""
    ug = [n for b in blocks for ln in b["lines"] for _, n in ln["anchors"]]
    chart = [c for s in sections for c in changes(s)]
    def score(sh):
        ps = {parse_chord(c) for c in chart}
        return sum(1 for n in ug if parse_chord(n) and ((parse_chord(n)[0] + sh) % 12, parse_chord(n)[1]) in ps)
    return max(range(12), key=lambda sh: (score(sh), -min(sh, 12 - sh)))


def assign(sections, blocks, shift):
    """Each vocal section → list of UG blocks (fresh, in order, or reused from an earlier section of the same kind)."""
    p, seen, out = 0, {}, []
    for s in sections:
        ch, b = changes(s), base(s["name"])
        if INSTR.search(s["name"]):   # chords only — unless UG's next block is this section with words (a sung intro)
            if p < len(blocks) and blocks[p]["heading"] and base(blocks[p]["heading"]) == b:
                out.append([blocks[p]]); p += 1
            else:
                out.append(None)
            continue
        reuse = None
        if b in seen:
            R = seen[b]
            reuse = max((R[:k] for k in range(1, len(R) + 1)), key=lambda x: sim(x, ch, shift))
        fresh, end = None, p
        if p < len(blocks):
            cands = []
            for k in range(1, 9):
                if p + k > len(blocks) or (k > 1 and blocks[p + k - 1]["heading"]):
                    break
                cands.append(blocks[p:p + k])
            fresh = max(cands, key=lambda x: sim(x, ch, shift))
            end = p + len(fresh)
        h = fresh[0]["heading"] if fresh else None
        if reuse is not None and fresh is not None:
            if h:   # a heading decides: same kind → new words (Charanam2), other kind → this is a repeat
                use_fresh = base(h) == b or base(h).startswith(b) or b.startswith(base(h))
            else:
                use_fresh = sim(fresh, ch, shift) > sim(reuse, ch, shift) + 0.1
        else:
            use_fresh = fresh is not None
        if use_fresh:
            out.append(fresh); p = end; seen.setdefault(b, fresh)
        elif reuse is not None:
            out.append(reuse)
        else:
            out.append(None)
    return out


def place(blocks, ch, shift):
    """Put the chart's chord changes on the words, in order, preferring UG's matching chord positions."""
    lines = [ln["text"] for b in blocks for ln in b["lines"]]
    pos = []  # (line, col, ug_chord or None)
    for li, b_ln in enumerate([ln for b in blocks for ln in b["lines"]]):
        starts = [m.start() for m in re.finditer(r'\S+', b_ln["text"])] or [0]
        ug_at = {}
        for c, nm in b_ln["anchors"]:   # snap UG's chord column to the start of the word it sits on (or the next word)
            w = max([x for x in starts if x <= c] or [starts[0]])
            if c > w + len(b_ln["text"][w:].split(' ')[0]):
                w = min([x for x in starts if x > c] or [w])
            ug_at.setdefault(w, nm)
        pos += [(li, c, ug_at.get(c)) for c in starts]
    n, m = len(ch), len(pos)
    while m < n:   # not enough places: extra chords at the end of the last line
        pos.append((len(lines) - 1, len(lines[-1]) + (m - len(pos)) + 1, None)); m += 1
    NEG = -1e9
    def gain(i, j):
        u = pos[j][2]
        return 3 if u and same(u, ch[i], shift) else (1 if u else 0)
    D = [[NEG] * (m + 1) for _ in range(n + 1)]; B = [[0] * (m + 1) for _ in range(n + 1)]
    for j in range(m + 1):
        D[0][j] = 0
    for i in range(1, n + 1):
        for j in range(i, m + 1):
            g = (100 if j == 1 else -1e6) if i == 1 else gain(i - 1, j - 1)   # the section's first chord sits on its first word
            skip, take = D[i][j - 1], D[i - 1][j - 1] + g
            D[i][j], B[i][j] = (take, 1) if take > skip else (skip, 0)   # ties → the earlier word
    i, j, at = n, m, {}
    while i > 0:
        if B[i][j]:
            at[j - 1] = ch[i - 1]; i -= 1
        j -= 1
    out = [list(t) for t in lines]
    for k in sorted(at, key=lambda k: (pos[k][0], -pos[k][1])):
        li, col, _ = pos[k]
        row = out[li]
        if col > len(row):
            row += [' '] * (col - len(row))
        row.insert(col, f'[{at[k]}]')
    return [''.join(r).rstrip() for r in out]


# ---------- song files ----------
def load_song(sid):
    p = os.path.join(ROOT, "songs", sid + ".json")
    if not os.path.exists(p):
        sys.exit(f"No song file songs/{sid}.json")
    return p, json.load(open(p, encoding="utf-8"))


def embed(song):
    """Keep index.html's built-in song list in step with songs/<id>.json."""
    p = os.path.join(ROOT, "index.html"); h = open(p, encoding="utf-8").read()
    j = h.find("const SONGS=") + len("const SONGS=")
    arr, end = json.JSONDecoder().raw_decode(h, j)
    arr = [song if x.get("id") == song["id"] else x for x in arr]
    open(p, "w", encoding="utf-8").write(h[:j] + json.dumps(arr, ensure_ascii=False) + h[end:])


def gate7(sections, text):
    """Same idea as buildLyricSync() in the app: section k ↔ the k-th sheet heading, chord-change order must match."""
    found = re.findall(r'^(.+?):\n((?:.+\n?)+)', text.split('\n\n', 1)[1], re.M)
    bad = []
    for k, s in enumerate(sections):
        name, body = found[k] if k < len(found) else ("", "")
        seq, prev = [], None
        for c in re.findall(r'\[([^\]]+)\]', body):
            if c != prev:
                seq.append(c); prev = c
        if name.strip().lower() != s["name"].lower() or seq != changes(s):
            bad.append(s["name"])
    return bad


def run(sid, url, a):
    path, doc = load_song(sid); song = doc["songs"][0]
    if url:
        song["lyricsSrc"] = {"label": "Ultimate Guitar", "url": url}
    src = song.get("lyricsSrc")
    if src and a.version and src.get("chords") != a.version:
        src["chords"] = a.version; url = url or src["url"]   # remember which chord version the sheet uses
    version = (src or {}).get("chords") or "simple"
    if not src:
        print(f"✗ {sid}: no Ultimate Guitar link yet — run: fetch_lyrics.py {sid} <UG link>"); return False
    content, ug_title = fetch_ug(src["url"])
    blocks = ug_blocks(content)
    sections = song["versions"][version]["sections"]
    shift = detect_shift(blocks, sections)
    parts = []
    for s, bl in zip(sections, assign(sections, blocks, shift)):
        ch = changes(s)
        body = "\n".join(place(bl, ch, shift)) if bl else " ".join(f"[{c}]" for c in ch)
        parts.append(f'{s["name"]}:\n{body}')
    vlabel = song["versions"][version].get("label", version)
    capo = f'capo {song["capo"]}' if song.get("capo") else "no capo"
    head = (f'{song["title"]} — {song.get("from") or song.get("artist", "")} · {capo} · chords: {vlabel} version\n'
            f'(lyrics: Ultimate Guitar — {ug_url(src["url"])} · kept on this device only)\n')
    text = head + "\n" + "\n\n".join(parts) + "\n"
    bad = gate7(sections, text)
    if a.dry_run:
        print(text); print("gate 7:", "OK" if not bad else f"mismatch in {bad}"); return not bad
    lp = os.path.join(ROOT, "songs", sid + "-lyrics.txt")
    open(lp, "w", encoding="utf-8").write(text)
    # stamp the refresh: devices that hold an older copy swap it for this sheet once (see lyrKey / sb-lyr-ver in the app)
    src["updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    json.dump(doc, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1); embed(song)
    msg = f'{"✓" if not bad else "✗"} {sid}: {len(parts)} sections from “{ug_title}” (UG chords shifted {shift} semitones to the chart) → songs/{sid}-lyrics.txt'
    if bad:
        msg += f"  · gate 7 mismatch in {bad}"
    keyf = os.path.join(ROOT, ".songbook-key")
    if not a.no_cloud and os.path.exists(keyf):
        key = open(keyf).read().strip()
        r = subprocess.run(["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "-X", "PUT", "-H", f"X-Songbook-Key: {key}",
                            "-H", "Content-Type: text/plain; charset=utf-8", "--data-binary", "@" + lp, f"{CLOUD}?id={sid}"],
                           capture_output=True, text=True)
        msg += f"  · cloud: {'saved' if r.stdout == '200' else 'failed (' + r.stdout + ')'}"
    print(msg)
    return not bad


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("song", nargs="?"); ap.add_argument("url", nargs="?")
    ap.add_argument("--all", action="store_true"); ap.add_argument("--no-cloud", action="store_true")
    ap.add_argument("--dry-run", action="store_true"); ap.add_argument("--version", choices=["simple", "intermediate", "band"], help="chord version for the sheet (default: the song's saved choice, else Easy)")
    a = ap.parse_args()
    if a.all:
        ids = sorted(f[:-5] for f in os.listdir(os.path.join(ROOT, "songs")) if f.endswith(".json"))
        ids = [i for i in ids if load_song(i)[1]["songs"][0].get("lyricsSrc")]
        ok = all([run(i, None, a) for i in ids]) if ids else print("No song has a lyricsSrc yet.")
    elif a.song:
        ok = run(a.song, a.url, a)
    else:
        ap.print_help(); sys.exit(2)
    sys.exit(0 if ok in (True, None) else 1)


if __name__ == "__main__":
    main()
