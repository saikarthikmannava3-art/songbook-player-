// ☁️ Songbook cloud backings — private Vercel Blob store, passphrase-protected.
// GET    /api/tracks            → your backing tracks, each with a short-lived signed download URL (6 h)
// POST   /api/tracks?name=F.m4a → a signed upload URL (15 min) for that file; the browser PUTs the audio straight to storage
// DELETE /api/tracks?name=F.m4a → remove a track
// Header: X-Songbook-Key: <passphrase>  (env SONGBOOK_KEY). Storage: env BLOB_READ_WRITE_TOKEN (linked store, access: private).
import { list, del, issueSignedToken, presignUrl } from "@vercel/blob";
import { timingSafeEqual } from "node:crypto";

const PREFIX = "backings/";
const okKey = k => { const a = Buffer.from(String(k || "")), b = Buffer.from(process.env.SONGBOOK_KEY || "\u0000unset"); return a.length === b.length && timingSafeEqual(a, b); };
const safeName = n => String(n || "").replace(/[^\w .()\-&,'+]/g, "").replace(/\s+/g, " ").trim().slice(0, 140);
const AUDIO = /\.(m4a|mp3|wav|aac|ogg|webm|mp4|flac)$/i;

export default async function handler(req, res) {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type, X-Songbook-Key");
  res.setHeader("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS");
  res.setHeader("Cache-Control", "no-store");
  if (req.method === "OPTIONS") return res.status(204).end();
  if (!okKey(req.headers["x-songbook-key"])) { await new Promise(r => setTimeout(r, 700)); return res.status(401).json({ error: "Wrong passphrase" }); }
  try {
    if (req.method === "GET") {
      const blobs = []; let cursor;
      do { const r = await list({ prefix: PREFIX, cursor, limit: 1000 }); blobs.push(...r.blobs); cursor = r.hasMore ? r.cursor : undefined; } while (cursor);
      const validUntil = Date.now() + 6 * 3600e3;
      const tracks = await Promise.all(blobs.filter(b => AUDIO.test(b.pathname)).map(async b => {
        const t = await issueSignedToken({ pathname: b.pathname, operations: ["get"], validUntil });
        const { presignedUrl } = await presignUrl(t, { operation: "get", pathname: b.pathname, access: "private", validUntil });
        return { name: b.pathname.slice(PREFIX.length), size: b.size, uploadedAt: b.uploadedAt, url: presignedUrl };
      }));
      return res.status(200).json({ tracks, validUntil });
    }
    const name = safeName(req.query && req.query.name);
    if (!AUDIO.test(name)) return res.status(400).json({ error: "Give an audio file name (.m4a, .mp3, …)" });
    const pathname = PREFIX + name;
    if (req.method === "POST") {
      const validUntil = Date.now() + 15 * 60e3, maximumSizeInBytes = 60e6;
      const t = await issueSignedToken({ pathname, operations: ["put"], validUntil, maximumSizeInBytes });
      const { presignedUrl } = await presignUrl(t, { operation: "put", pathname, access: "private", validUntil, maximumSizeInBytes, allowOverwrite: true });
      return res.status(200).json({ uploadUrl: presignedUrl, pathname });
    }
    if (req.method === "DELETE") {
      const r = await list({ prefix: pathname, limit: 10 }); const b = r.blobs.find(x => x.pathname === pathname);
      if (b) await del(b.url);
      return res.status(200).json({ deleted: !!b });
    }
    return res.status(405).json({ error: "Method not allowed" });
  } catch (e) { return res.status(500).json({ error: String((e && e.message) || e) }); }
}
