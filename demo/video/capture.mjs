// Renders every visual segment of the demo video.
//   node capture.mjs build/data.json
// Scene acts (Bouncer OFF / ON) are stepped deterministically frame by frame from live/index.html;
// cards (title, terminal, evidence, close) are rendered from cards.html as stills with durations.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { launch, Capture } from './scene_lib.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const data = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const B = data.buildDir;
const FPS = data.fps || 30;
const SCENE_URL = pathToFileURL(path.resolve(HERE, '..', '..', 'live', 'index.html')).href;
const CARDS_URL = pathToFileURL(path.join(HERE, 'cards.html')).href;
const segments = [];

const SCENE_CSS = `
header{display:none}main{display:block;max-width:none;padding:0;margin:0}aside{display:none}
main>section{position:relative}
.stage{border:0;border-radius:0;width:1280px;height:640px;aspect-ratio:auto}
.narrator,.report{display:none!important}
#ask{position:absolute;left:290px;top:210px;width:700px;z-index:30;margin:0}
#vbar{position:fixed;left:0;right:0;bottom:0;height:80px;background:#070b1d;border-top:2px solid #2a3563;display:flex;align-items:center;gap:18px;padding:0 22px;z-index:99;font-family:"Avenir Next","Segoe UI",system-ui,sans-serif;color:#eaf0ff}
#vpill{flex:none;width:158px;text-align:center;padding:10px 0;border-radius:999px;font-weight:900;letter-spacing:1.5px;font-size:15px;border:2px solid}
#vpill.on{color:#062;background:#47e6a8;border-color:#47e6a8}
#vpill.off{color:#fff;background:#8a1f30;border-color:#ff4d63}
#vcap{flex:1;min-width:0}
#vm{font-size:22px;font-weight:700;line-height:1.2}
#vs{font-size:14px;color:#8d99c7;margin-top:3px;line-height:1.25}
#vtal{flex:none;width:400px;text-align:right}
#vt1{font-size:14px;font-weight:800;white-space:nowrap}
#vt2{font-size:11px;color:#8d99c7;margin-top:4px;line-height:1.3}
#vtag{position:fixed;left:14px;top:12px;z-index:99;background:#0b1030dd;border:1px solid #2a3563;color:#8d99c7;border-radius:999px;font:700 11px "Avenir Next",system-ui,sans-serif;letter-spacing:1px;padding:5px 11px}
`;

// runs inside the page after load
const SCENE_SETUP = (bouncerOn) => {
  const _h = handle;
  handle = async function (d, i, ...r) { window.__cur = i; return _h.call(this, d, i, ...r); };
  window.__cur = -1;
  const bar = document.createElement('div'); bar.id = 'vbar';
  bar.innerHTML = '<span id="vpill"></span><div id="vcap"><div id="vm"></div><div id="vs"></div></div><div id="vtal"><div id="vt1"></div><div id="vt2">Visualization of the same scenario: a scripted replay, not a live model call</div></div>';
  document.body.appendChild(bar);
  const tag = document.createElement('div'); tag.id = 'vtag'; tag.textContent = 'SCRIPTED VISUALIZATION'; document.body.appendChild(tag);
  window.__cap = (m, s) => { document.getElementById('vm').textContent = m || ''; document.getElementById('vs').textContent = s || ''; };
  window.__state = () => {
    const on = bouncerOn;
    const p = document.getElementById('vpill'); p.className = on ? 'on' : 'off'; p.textContent = on ? 'BOUNCER ON' : 'BOUNCER OFF';
    const g = id => document.getElementById(id).textContent;
    const t1 = document.getElementById('vt1');
    if (on) t1.innerHTML = `<span style="color:#47e6a8">Let in ${g('cIn')}</span> · <span style="color:#ffc857">Asked ${g('cAsk')}</span> · <span style="color:#ff4d63">Turned away ${g('cOut')}</span> · <span style="color:#47e6a8">Got through ${g('cBad')}</span>`;
    else t1.innerHTML = `<span style="color:${+g('cBad') ? '#ff4d63' : '#8d99c7'}">Bad actions that got through: ${g('cBad')}</span>`;
    return { vt, cur: window.__cur, res: document.getElementById('result').style.display, resText: document.getElementById('result').textContent, ask: document.getElementById('ask').style.display, bad: +g('cBad') };
  };
  setBouncer(bouncerOn);
};

async function sceneAct(browser, name, spec) {
  const page = await browser.newPage();
  const cap = new Capture(page, path.join(B, 'frames', name), FPS);
  await cap.openScene(SCENE_URL, SCENE_CSS, null);
  await page.evaluate(SCENE_SETUP, spec.bouncerOn);
  const setSpeed = (s) => page.evaluate((s) => { userSpeed = s; speed = s; }, s);
  let st = await cap.frame();
  let last = -99, askFrames = 0, safety = 0;
  for (;;) {
    if (st.cur !== last) {
      last = st.cur;
      const c = spec.captions.byDecision[String(st.cur)] || (st.cur < 0 ? spec.captions.pre : null);
      if (c) await page.evaluate((m, s) => window.__cap(m, s), c[0], c[1]);
      await setSpeed(spec.speed[String(st.cur)] ?? 1);
    }
    if (st.res === 'block') break;
    if (st.ask === 'block') { askFrames++; if (askFrames === Math.round(FPS * (spec.askWaitSec || 2))) await page.evaluate(() => document.getElementById('askYes').click()); }
    if (++safety > FPS * 240) throw new Error('scene did not finish: ' + name);
    st = await cap.frame();
  }
  await setSpeed(1);
  const endMain = spec.captions.endUseResultText ? st.resText : spec.captions.end[0];
  await page.evaluate((m, s) => window.__cap(m, s), endMain, spec.captions.end[1]);
  await cap.hold(spec.endHoldSec || 3);
  segments.push({ name, type: 'frames', dir: path.join(B, 'frames', name), fps: FPS, count: cap.n });
  console.log(name, 'frames', cap.n, 'seconds', (cap.n / FPS).toFixed(1));
  await page.close();
}

async function bgShot(browser) {
  const page = await browser.newPage();
  const cap = new Capture(page, path.join(B, 'bg'), FPS);
  await cap.openScene(SCENE_URL, SCENE_CSS, null);
  await page.evaluate(() => { setBouncer(true); });
  await cap.hold(0.5, false);
  const f = path.join(B, 'bg.jpg');
  await page.screenshot({ path: f, type: 'jpeg', quality: 90, clip: { x: 0, y: 0, width: 1280, height: 640 } });
  await page.close();
  return f;
}

async function cards(browser, bgFile) {
  const page = await browser.newPage();
  await page.setViewport({ width: 1280, height: 720, deviceScaleFactor: 1 });
  await page.goto(CARDS_URL, { waitUntil: 'load' });
  data.bg = pathToFileURL(bgFile).href;
  await page.evaluate((d) => { window.DATA = d; }, data);
  const dir = path.join(B, 'stills'); fs.mkdirSync(dir, { recursive: true });
  let k = 0;
  const shot = async (scene, params) => {
    await page.evaluate((s, p) => window.show(s, p), scene, params);
    const f = path.join(dir, `s_${String(k++).padStart(3, '0')}.png`);
    await page.screenshot({ path: f, type: 'png' });
    return f;
  };
  const D = data.durations;
  segments.push({ name: 'title', type: 'stills', items: [{ file: await shot('title'), dur: D.title }] });
  for (let pi = 0; pi < data.terminal.pages.length; pi++) {
    const pg = data.terminal.pages[pi];
    const groups = Math.max(...pg.lines.map((l) => l.g)) + 1;
    const total = D['term' + pi], reveal = total * 0.62, hold = total - reveal;
    const items = [];
    const per = reveal / groups;
    for (let g = 0; g < groups; g++) {
      const n = pg.lines.filter((l) => l.g <= g).length;
      items.push({ file: await shot('term', { page: pi, n, cursor: true }), dur: per });
    }
    items.push({ file: await shot('term', { page: pi }), dur: hold });
    segments.push({ name: 'term' + pi, type: 'stills', items });
  }
  segments.push({ name: 'ev1', type: 'stills', items: [{ file: await shot('ev1'), dur: D.ev1 }] });
  segments.push({ name: 'ev2', type: 'stills', items: [{ file: await shot('ev2'), dur: D.ev2 }] });
  segments.push({ name: 'close', type: 'stills', items: [{ file: await shot('close'), dur: D.close }] });
  await page.close();
}

fs.rmSync(path.join(B, 'frames'), { recursive: true, force: true });
const browser = await launch();
try {
  const bg = await bgShot(browser);
  await cards(browser, bg);
  await sceneAct(browser, 'act1', data.acts.act1);
  await sceneAct(browser, 'act2', data.acts.act2);
} finally { await browser.close(); }
fs.writeFileSync(path.join(B, 'segments.json'), JSON.stringify(segments, null, 1));
console.log('wrote segments.json');
