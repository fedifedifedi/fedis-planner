// End-to-end test of the planner in a real browser (Edge or Chrome, headless), driven through the Chrome
// DevTools Protocol with Node's built-in WebSocket: no dependency.
//
// Prerequisites: API on http://127.0.0.1:8000 and interface on http://localhost:3000 (e.g. .\dev.ps1).
// Usage:  cd frontend; npm run test:e2e
//         node tests/e2e.mjs [--url http://localhost:3000] [--browser "C:\...\msedge.exe"]
// Outputs (screenshots, printed PDF) go to frontend/tests/output/ (git-ignored). Exit code 1 if a check fails.
import { spawn } from "node:child_process";
import { existsSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const args = process.argv.slice(2);
const opt = (name, fallback) => (args.includes(name) ? args[args.indexOf(name) + 1] : fallback);
const BASE = opt("--url", "http://localhost:3000");
const OUT = join(dirname(fileURLToPath(import.meta.url)), "output");
const PORT = 9400 + Math.floor(Math.random() * 400);
const BROWSERS = [
  opt("--browser", process.env.BROWSER),
  "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
  "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
  "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
  "/usr/bin/google-chrome",
  "/usr/bin/chromium",
].filter(Boolean);

const browserPath = BROWSERS.find((p) => existsSync(p));
if (!browserPath) {
  console.error("No Edge/Chrome found: pass --browser <path> or set BROWSER.");
  process.exit(2);
}
rmSync(join(OUT, "profile"), { recursive: true, force: true });
mkdirSync(OUT, { recursive: true });

const browser = spawn(browserPath, [
  "--headless=new", `--remote-debugging-port=${PORT}`, "--window-size=1440,1000", "--no-first-run",
  `--user-data-dir=${join(OUT, "profile")}`, "about:blank",
]);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let failures = 0;
function check(label, ok, detail = "") {
  console.log(`${ok ? "PASS" : "FAIL"}  ${label}${detail ? `  (${detail})` : ""}`);
  if (!ok) failures++;
}

let target;
for (let i = 0; i < 50 && !target; i++) {
  try {
    target = (await (await fetch(`http://127.0.0.1:${PORT}/json`)).json()).find((t) => t.type === "page");
  } catch {}
  await sleep(300);
}
const ws = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((r) => ws.addEventListener("open", r));
let seq = 0;
const pending = new Map();
ws.addEventListener("message", (e) => {
  const msg = JSON.parse(e.data);
  if (msg.id && pending.has(msg.id)) {
    pending.get(msg.id)(msg);
    pending.delete(msg.id);
  }
});
const send = (method, params = {}) =>
  new Promise((resolve) => {
    const id = ++seq;
    pending.set(id, resolve);
    ws.send(JSON.stringify({ id, method, params }));
  });
const evaluate = async (expression) =>
  (await send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true })).result?.result?.value;
async function waitFor(expression, timeout = 90000) {
  const t0 = Date.now();
  while (Date.now() - t0 < timeout) {
    if (await evaluate(expression)) return true;
    await sleep(250);
  }
  return false;
}
const clickButton = (text) =>
  evaluate(`(() => { const b = [...document.querySelectorAll('button')].find(b => b.textContent.trim().startsWith(${JSON.stringify(text)}) && !b.disabled); if (!b) return false; b.click(); return true; })()`);
const setSelect = (optionPredicate, value) =>
  evaluate(`(() => {
    const sel = [...document.querySelectorAll('select')].find(s => [...s.options].some(o => ${optionPredicate}));
    if (!sel) return false;
    Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set.call(sel, ${value});
    sel.dispatchEvent(new Event('change', { bubbles: true }));
    return true; })()`);
async function screenshot(name) {
  const res = await send("Page.captureScreenshot", { format: "png" });
  writeFileSync(join(OUT, `${name}.png`), Buffer.from(res.result.data, "base64"));
}

try {
  await send("Page.enable");

  // ---- home: marked animations end with everything visible
  await send("Page.navigate", { url: `${BASE}/` });
  check("home loads", await waitFor("document.querySelector('.home-title') !== null", 30000));
  check(
    "home illustration visible after its animation",
    await waitFor("[...document.querySelectorAll('.hero-session')].filter(e => getComputedStyle(e).opacity > 0.9).length === document.querySelectorAll('.hero-session').length && document.querySelectorAll('.hero-session').length > 0", 10000),
  );
  await screenshot("1-home");

  // ---- planner: load and solve (CSS cascade)
  await send("Page.navigate", { url: `${BASE}/planner` });
  await waitFor("[...document.querySelectorAll('button')].some(b => b.textContent.includes('Petite école'))", 30000);
  await clickButton("Clair");
  await clickButton("Petite école");
  check("sample instance loaded", await waitFor("document.body.textContent.includes('small-s42')", 30000));
  await clickButton("Résoudre");
  check("solve shows sessions", await waitFor("document.querySelectorAll('.session').length > 0", 90000));
  check("all sessions visible after the cascade", await waitFor("[...document.querySelectorAll('.session')].every(e => getComputedStyle(e).opacity > 0.99)", 5000));
  await screenshot("2-solved");

  // ---- exports: .ics through the real button, PDF through the print stylesheet
  await evaluate(`(() => { window.__ics = null; const orig = URL.createObjectURL; URL.createObjectURL = (b) => { b.text().then(t => window.__ics = t); return orig(b); }; return true })()`);
  await clickButton("Exporter .ics");
  const gotIcs = await waitFor("window.__ics !== null", 20000);
  const ics = gotIcs ? await evaluate("window.__ics") : "";
  const events = (ics.match(/BEGIN:VEVENT/g) || []).length;
  check(".ics export", ics.startsWith("BEGIN:VCALENDAR") && events > 0, `${events} events`);
  const pdf = await send("Page.printToPDF", { landscape: true, printBackground: true, preferCSSPageSize: true });
  const pdfBytes = Buffer.from(pdf.result?.data ?? "", "base64");
  writeFileSync(join(OUT, "timetable.pdf"), pdfBytes);
  check("PDF printed (grid only)", pdfBytes.length > 10000, `${pdfBytes.length} bytes`);

  // ---- replanning: the teacher of the first displayed session is absent on that session's day
  //      -> at least one move, Flip glide, highlight, no leftover transform
  const first = await evaluate("(() => { const s = document.querySelector('.session'); return s ? { title: s.title, day: s.closest('.grid-cell').title.split(' ')[0] } : null })()");
  const teacher = first?.title.split("— ")[1]?.split(" · ")[0] ?? "";
  await setSelect(`o.text === ${JSON.stringify(teacher)}`, `[...sel.options].find(o => o.text === ${JSON.stringify(teacher)}).value`);
  await evaluate(`(() => { for (const b of document.querySelectorAll('input[type=checkbox]')) { const want = b.parentElement.textContent.trim() === ${JSON.stringify(first?.day ?? "")}; if (b.checked !== want) b.click(); } return true })()`);
  await sleep(200);
  await clickButton("Replanifier");
  check("replanning done", await waitFor("[...document.querySelectorAll('[data-slot=card-title]')].some(e => e.textContent.includes('déplacée'))", 90000), `absent: ${teacher}, ${first?.day}`);
  const header = await evaluate("[...document.querySelectorAll('[data-slot=card-title]')].map(e => e.textContent).find(t => t.includes('déplacée')) ?? ''");
  const [moved, minimum] = (header.match(/\d+/g) ?? []).map(Number);
  check("at least one session moved, never fewer than the lower bound", minimum >= 1 && moved >= minimum, header);
  check("moved sessions highlighted", (await evaluate("document.querySelectorAll('.session[data-moved]').length")) >= 1);
  await sleep(2500);
  check(
    "no leftover transform after the Flip glide",
    (await evaluate("[...document.querySelectorAll('.session')].filter(e => { const m = getComputedStyle(e).transform; return m !== 'none' && m !== 'matrix(1, 0, 0, 1, 0, 0)'; }).length")) === 0,
  );
  await screenshot("3-replanned");

  // ---- infeasible instance: minimal conflicting set and hover highlight
  await evaluate("document.querySelector('details').open = true");
  await setSelect("o.value === 'teacher_availability'", "'teacher_availability'");
  await clickButton("Générer");
  await waitFor("document.body.textContent.includes('teacher_availability')", 30000);
  await clickButton("Résoudre");
  check("explanation shown", await waitFor("document.body.textContent.includes('Pourquoi il n')", 90000));
  const conflicts = await evaluate("document.querySelectorAll('li button').length");
  check("minimal set of 3 constraints", conflicts === 3, `${conflicts} listed`);
  check("explanation states the hours assumption", await evaluate("document.body.textContent.includes('tous les cours doivent avoir leurs heures')"));
  await evaluate("(() => { const b = [...document.querySelectorAll('li button')].find(b => b.textContent.includes('disponible')); b?.dispatchEvent(new MouseEvent('mouseover', { bubbles: true })); return true })()");
  await sleep(400);
  const forbidden = await evaluate("document.querySelectorAll('.grid-cell[data-forbidden]').length");
  const hot = await evaluate("document.querySelectorAll('.grid-cell[data-hot]').length");
  check("hovering a constraint highlights slots", forbidden > 0 && hot > 0, `${hot} available, ${forbidden} forbidden`);
  await screenshot("4-conflict-hover");

  // ---- dark theme
  await clickButton("Sombre");
  check("dark theme", await evaluate("document.documentElement.classList.contains('dark')"));
  await sleep(800); // let colour transitions finish before the screenshot
  await screenshot("5-dark");
} catch (error) {
  check("no unexpected error", false, String(error));
} finally {
  ws.close();
  browser.kill();
}

console.log(failures ? `\n${failures} check(s) failed. Screenshots: ${OUT}` : `\nAll checks passed. Screenshots and PDF: ${OUT}`);
process.exit(failures ? 1 : 0);
