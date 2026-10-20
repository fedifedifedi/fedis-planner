// Latest stable npm version of each package published before a cutoff (default: 14 days ago).
// `npm view <pkg> version --before` ignores --before, so dates are read from the registry `time` field.
// Usage: node scripts/npm_versions_before.mjs [--days 14] [--major next=16] pkg1 pkg2 ...
import { execFileSync } from "node:child_process";

const args = process.argv.slice(2);
let days = 14;
const majors = {};
const pkgs = [];
for (let i = 0; i < args.length; i++) {
  if (args[i] === "--days") days = Number(args[++i]);
  else if (args[i] === "--major") {
    const [name, major] = args[++i].split("=");
    majors[name] = major;
  } else pkgs.push(args[i]);
}
const cutoff = Date.now() - days * 86400_000;
const npm = process.platform === "win32" ? "npm.cmd" : "npm";

for (const pkg of pkgs) {
  const time = JSON.parse(execFileSync(npm, ["view", pkg, "time", "--json"], { encoding: "utf8", shell: true }));
  const candidates = Object.entries(time)
    .filter(([v, d]) => /^\d+\.\d+\.\d+$/.test(v) && Date.parse(d) < cutoff)
    .filter(([v]) => !majors[pkg] || v.split(".")[0] === majors[pkg])
    .sort((a, b) => Date.parse(a[1]) - Date.parse(b[1]));
  const last = candidates.at(-1);
  console.log(`${pkg.padEnd(28)} ${last ? `${last[0].padEnd(10)} ${last[1].slice(0, 10)}` : "none"}`);
}
