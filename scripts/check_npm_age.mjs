// Audit every package of frontend/package-lock.json: flag versions published less than N days ago.
// Usage: node scripts/check_npm_age.mjs [--days 14]   (exit code 1 on violation)
import { readFileSync } from "node:fs";

const days = process.argv.includes("--days") ? Number(process.argv[process.argv.indexOf("--days") + 1]) : 14;
const cutoff = Date.now() - days * 86400_000;
const lock = JSON.parse(readFileSync(new URL("../frontend/package-lock.json", import.meta.url), "utf8"));

const pkgs = new Map();
for (const [path, info] of Object.entries(lock.packages)) {
  if (!path || !info.version) continue;
  const name = path.slice(path.lastIndexOf("node_modules/") + "node_modules/".length);
  pkgs.set(`${name}@${info.version}`, { name, version: info.version });
}

let bad = 0;
for (const { name, version } of [...pkgs.values()].sort((a, b) => a.name.localeCompare(b.name))) {
  let date;
  for (let attempt = 0; attempt < 5 && !date; attempt++) {
    try {
      const res = await fetch(`https://registry.npmjs.org/${name.replace("/", "%2F")}`, {
        headers: { accept: "application/vnd.npm.install-v1+json; q=1.0, application/json; q=0.8" },
      });
      const meta = await res.json();
      date = meta.time?.[version];
      if (!date) {
        const full = await (await fetch(`https://registry.npmjs.org/${name.replace("/", "%2F")}`)).json();
        date = full.time?.[version];
      }
    } catch {
      await new Promise((r) => setTimeout(r, 2000 * (attempt + 1)));
    }
  }
  const tooRecent = !date || Date.parse(date) > cutoff;
  if (tooRecent) bad++;
  console.log(`${tooRecent ? "TOO RECENT" : "ok        "} ${name}@${version} ${date ? date.slice(0, 10) : "?"}`);
}
console.log(bad ? `\n${bad} package(s) violate the ${days}-day rule` : `\nAll ${pkgs.size} packages published more than ${days} days ago.`);
process.exit(bad ? 1 : 0);
