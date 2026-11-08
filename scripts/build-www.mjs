// Copies the website into www/ for the iPhone app (Capacitor). Only the app itself: no audio, stems, lyrics or PDFs.
import { cpSync, mkdirSync, rmSync, readdirSync, existsSync, readFileSync, writeFileSync } from "node:fs";
const out = "www";
rmSync(out, { recursive: true, force: true }); mkdirSync(out + "/songs", { recursive: true });
for (const f of ["index.html", "manifest.webmanifest"]) cpSync(f, out + "/" + f);
cpSync("images", out + "/images", { recursive: true });
for (const f of readdirSync("songs")) if (f.endsWith(".json")) cpSync("songs/" + f, out + "/songs/" + f);
// Your own iPhone build only: bake in the cloud passphrase (from .songbook-key, never committed or deployed) so the app is always linked.
if (existsSync(".songbook-key")) {
  const key = readFileSync(".songbook-key", "utf8").trim();
  writeFileSync(out + "/cloud-key.js", "try{if(!localStorage.getItem('sb-cloud-key'))localStorage.setItem('sb-cloud-key',JSON.stringify(" + JSON.stringify(key) + "))}catch(e){}\n");
  const html = readFileSync(out + "/index.html", "utf8").replace("<head>", '<head><script src="cloud-key.js"></script>');
  writeFileSync(out + "/index.html", html);
}
console.log("www/ ready:", readdirSync(out).join(", "), existsSync(out + "/images/icons/icon-512.png") ? "(icons ok)" : "");
