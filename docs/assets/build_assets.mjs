// Renders docs/assets/logo.png, logo-mark.png and how-it-works.png. Run capture_frames.mjs first.
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(path.join(here, "../../demo/video/package.json"));
const puppeteer = require("puppeteer-core");
const CHROME = process.env.CHROME_PATH || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const browser = await puppeteer.launch({ executablePath: CHROME, headless: "new", args: ["--no-sandbox", "--allow-file-access-from-files"] });
const shot = async (file, sel, out, scale = 1) => {
  const page = await browser.newPage();
  await page.setViewport({ width: 1700, height: 1300, deviceScaleFactor: scale });
  await page.goto("file://" + path.join(here, file), { waitUntil: "load" });
  await new Promise(r => setTimeout(r, 400));
  await (await page.$(sel)).screenshot({ path: path.join(here, out), omitBackground: false });
  await page.close();
  console.log("wrote", out);
};
await shot("logo.html", "#banner", "logo.png", 1);
await shot("logo.html", "#icon", "logo-mark.png", 1);
await shot("explainer.html", "#card", "how-it-works.png", 1);
await browser.close();
