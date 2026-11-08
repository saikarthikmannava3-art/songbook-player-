// ☁️ Songbook cloud lyrics — private Vercel Blob store, passphrase-protected (same as /api/tracks).
// GET  /api/lyrics            → { ids: [...] } songs that have lyrics in the cloud
// GET  /api/lyrics?id=7-years → the lyrics sheet (text, ChordPro-style [C]word)
// PUT  /api/lyrics?id=7-years → save the sheet (text body, ≤ 200 KB)
import { list, get, put } from "@vercel/blob";
import { timingSafeEqual } from "node:crypto";

const PREFIX = "lyrics/";
const okKey = k => { const a = Buffer.from(String(k || "")), b = Buffer.from(process.env.SONGBOOK_KEY || "\u0000unset"); return a.length === b.length && timingSafeEqual(a, b); };
const safeId = s => String(s || "").toLowerCase().replace(/[^a-z0-9-]/g, "").slice(0, 80);
async function bodyText(req) {
  if (typeof req.body === "string") return req.body;
  if (req.body && Buffer.isBuffer(req.body)) return req.body.toString("utf8");
  const chunks = []; for await (const c of req) chunks.push(c); return Buffer.concat(chunks).toString("utf8");
}

export default async function handler(req, res) {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type, X-Songbook-Key");
  res.setHeader("Access-Control-Allow-Methods", "GET, PUT, OPTIONS");
  res.setHeader("Cache-Control", "no-store");
  if (req.method === "OPTIONS") return res.status(204).end();
  if (!okKey(req.headers["x-songbook-key"])) { await new Promise(r => setTimeout(r, 700)); return res.status(401).json({ error: "Wrong passphrase" }); }
  try {
    const id = safeId(req.query && req.query.id);
    if (req.method === "GET" && !id) {
      const ids = []; let cursor;
      do { const r = await list({ prefix: PREFIX, cursor, limit: 1000 }); ids.push(...r.blobs.map(b => b.pathname.slice(PREFIX.length).replace(/\.txt$/, ""))); cursor = r.hasMore ? r.cursor : undefined; } while (cursor);
      return res.status(200).json({ ids });
    }
    if (!id) return res.status(400).json({ error: "Give a song id" });
    const pathname = PREFIX + id + ".txt";
    if (req.method === "GET") {
      const r = await get(pathname, { access: "private", useCache: false });
      if (!r || r.statusCode !== 200) return res.status(404).json({ error: "No lyrics for this song yet" });
      const text = await new Response(r.stream).text();
      res.setHeader("Content-Type", "text/plain; charset=utf-8"); return res.status(200).send(text);
    }
    if (req.method === "PUT") {
      const text = await bodyText(req);
      if (!text.trim()) return res.status(400).json({ error: "Empty sheet" });
      if (Buffer.byteLength(text) > 200e3) return res.status(413).json({ error: "Too large" });
      await put(pathname, text, { access: "private", allowOverwrite: true, addRandomSuffix: false, contentType: "text/plain; charset=utf-8", cacheControlMaxAge: 60 });
      return res.status(200).json({ saved: id, bytes: Buffer.byteLength(text) });
    }
    return res.status(405).json({ error: "Method not allowed" });
  } catch (e) { return res.status(500).json({ error: String((e && e.message) || e) }); }
}
