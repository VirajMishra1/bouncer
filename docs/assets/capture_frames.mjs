// Captures five real moments from the Bouncer Live scene (live/index.html) for the explainer image.
// Uses the page's own deterministic stepping, so the frames are exactly what the product draws.
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";
import fs from "node:fs";

const here = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(path.join(here, "../../demo/video/package.json"));
const puppeteer = require("puppeteer-core");
const CHROME = process.env.CHROME_PATH || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const out = path.join(here, "frames");
fs.mkdirSync(out, { recursive: true });

const SHOTS = [
  { name: "1-ask",    pred: "document.getElementById('narrator').textContent.startsWith('Step 1')", extra: 1100 },
  { name: "2-yes",    pred: "[...document.querySelectorAll('#fx text')].some(t=>/ON THE LIST/.test(t.textContent))", extra: 500 },
  { name: "3-trick",  pred: "typeof attacker!=='undefined' && attacker && attacker.shown && attacker.rise>0.97", extra: 600 },
  { name: "4-check",  pred: "document.getElementById('narrator').textContent.startsWith('Step 4') && [...document.querySelectorAll('#fx text')].some(t=>/CHECKING/.test(t.textContent))", extra: 350 },
  { name: "5-no",     pred: "[...document.querySelectorAll('#fx text')].some(t=>/NOT TONIGHT/.test(t.textContent)) && !document.getElementById('cutin').classList.contains('on')", extra: 450 },
];

const browser = await puppeteer.launch({ executablePath: CHROME, headless: "new", args: ["--no-sandbox", "--hide-scrollbars"] });
const page = await browser.newPage();
await page.setViewport({ width: 1500, height: 1000, deviceScaleFactor: 1.5 });
await page.goto("file://" + path.join(here, "../../live/index.html"), { waitUntil: "load" });
await page.evaluate(() => {
  window.__adv = ms => { for (let t = 0; t < ms; t += 16) { if (!paused) step(16); render(16); } };
  window.__until = async (predSrc, extra) => {
    const pred = new Function("return (" + predSrc + ")");
    for (let t = 0; t < 240000; t += 32) {
      if (pred()) { window.__adv(extra); return true; }
      window.__adv(32);
      await new Promise(r => setTimeout(r, 0));
    }
    return false;
  };
});
for (const shot of SHOTS) {
  await page.evaluate(() => { paused = false; });
  const ok = await page.evaluate((p, e) => window.__until(p, e), shot.pred, shot.extra);
  if (!ok) console.error("moment not reached:", shot.name);
  await page.evaluate(() => { paused = true; });   // freeze the scene: the page's own frame loop keeps running in real time
  await new Promise(r => setTimeout(r, 900));      // let real-time CSS (pop-in, letterbox) settle on the frozen moment
  const stage = await page.$("#stage");
  await stage.screenshot({ path: path.join(out, shot.name + ".png") });
  console.log("captured", shot.name);
}
await browser.close();
