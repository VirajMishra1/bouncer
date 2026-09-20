// Renders the 28-second Bouncer trailer frame by frame from live/index.html with a virtual clock.
//   node capture.mjs [--fps 60] [--max 9999] [--out build]
// Writes JPEG frames to <out>/frames and the sound-design cue list to <out>/events.json.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { launch, Capture } from './scene_lib.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const arg = (k, d) => { const i = process.argv.indexOf('--' + k); return i > 0 ? process.argv[i + 1] : d; };
const FPS = +arg('fps', 60), MAXF = +arg('max', 99999), OUT = path.resolve(arg('out', path.join(HERE, 'build')));
const SCENE = pathToFileURL(path.resolve(HERE, '..', '..', 'live', 'index.html')).href;
const LOGO = pathToFileURL(path.resolve(HERE, '..', '..', 'docs', 'assets', 'logo-mark.png')).href;
fs.rmSync(path.join(OUT, 'frames'), { recursive: true, force: true });

const b = await launch();
const page = await b.newPage();
const cap = new Capture(page, path.join(OUT, 'frames'), FPS, 92);
await cap.openScene(SCENE, fs.readFileSync(path.join(HERE, 'overlay.css'), 'utf8'), null);
await page.setViewport({ width: 1920, height: 1080, deviceScaleFactor: 1 });
await page.evaluate(`(${fs.readFileSync(path.join(HERE, 'overlay.js'), 'utf8')})(${JSON.stringify({ logoUrl: LOGO })})`);
await page.evaluate(() => { window.__camUpdate(); });

const events = []; const seen = new Set();
const T = () => cap.n / FPS;
const mark = (name) => { events.push({ t: +T().toFixed(3), name }); console.log(T().toFixed(2).padStart(6), name); };
const once = (key, fn) => { if (!seen.has(key)) { seen.add(key); mark(key); fn && fn(); } };
const ev = (fn, ...a) => page.evaluate(fn, ...a);
const cam = (s, fx, fy, dur, e) => ev((s, fx, fy, d, e) => window.__camTo(s, fx, fy, d, e), s, fx, fy, dur, e);
const tv = (name, ...a) => ev((n, a) => window.__TV[n](...a), name, a);
const prop = (n, v, d, e) => ev((n, v, d, e) => window.__prop(n, v, d, e), n, v, d, e);
const setSpeed = (s) => ev((s) => { userSpeed = s; speed = s; }, s);

let spd = 0.04, target = 0.04;
const phaseAt = {}; // when each phase began (frames)
let stage = 'scene';   // scene -> explain -> end -> done

// ---- t=0: cold open over the blurred, dimmed pub --------------------------------------------
await ev(() => { window.__prop('blur', 16, 1, 'lin'); window.__dimTo(0.55, 1); });
await cam(1.16, 960, 480, 1, 'lin');
await setSpeed(spd);
await ev(() => window.__camUpdate());
await cap.frame(false); await ev(() => window.__camUpdate());

let st;
for (let i = 0; i < MAXF; i++) {
  const t = T();
  // ---------------- cold open ----------------
  if (t >= 0.25) once('intro1', () => tv('intro', 'AI agents read everything.'));
  if (t >= 1.35) once('intro2', () => { tv('intro2', 'Some of it gives *orders.*'); });
  if (t >= 1.9) once('intro-glitch', () => ev(() => window.__TV.glitch()));
  if (t >= 2.75) once('intro-out', async () => { await tv('introOut'); await prop('blur', 0, 520, 'out'); await ev(() => window.__dimTo(0, 500)); await cam(1.0, 960, 480, 1400, 'expo'); await tv('flash'); });

  // ---------------- scene ----------------
  if (stage === 'scene') {
    if (t >= 2.75) {
      // speed policy
      const s = st || {};
      const c = s.cur ?? -1;
      if (c <= 0) target = s.checking ? 1.0 : (s.allowed ? 2.4 : 2.6);
      else if (c === 1) target = 6;
      else if (c === 2) target = s.inj ? 1.5 : (s.checking ? 1.4 : 4.5);
      else if (c === 3) target = s.cutin ? 1.0 : (s.notTonight ? 1.6 : (s.checking ? 1.0 : 3.2));
      else if (c === 4) target = s.cutin ? 1.3 : (s.notTonight ? 2.6 : (s.checking ? 1.6 : 4));
      else target = s.cutin ? 1.4 : 2.6;
    }
    spd += (target - spd) * 0.14; await setSpeed(spd);

    if (st) {
      const c = st.cur;
      if (t >= 2.9 && c <= 0 && !st.checking) once('goal', async () => { await tv('cap', '01 · You ask', 'Give the agent a job.'); await cam(2.05, 400, 120, 900, 'expo'); });
      if (st.checking && c === 0) once('check0', async () => { await tv('capOut'); await cam(1.0, 960, 480, 700, 'expo'); setTimeout(() => {}, 0); });
      if (st.checking && c === 0) once('check0cap', () => tv('cap', '02 · The door', 'Every action gets checked.'));
      if (st.allowed && c === 0) once('allow0', async () => { await tv('cap', 'Bouncer says', 'Asked for it? Come in.', 'green'); await ev(() => { window.__punch(0.04, 500); }); });
      if (c === 1) once('ff', async () => { await tv('capOut'); });
      if (c === 2 && !st.inj) once('c2', () => {});
      if (st.inj && c === 2) once('inj', async () => { await tv('cap', '03 · The trap', 'A hidden line inside an email.', 'red'); await ev(() => { window.__TV.glitch(); window.__shake(10, 500); }); await cam(1.22, 760, 520, 2400, 'io'); });
      if (st.checking && c === 3) once('check3', async () => { await tv('capOut'); await cam(1.0, 960, 480, 500, 'expo'); });
      if (st.cutin && c === 3) once('block3', async () => { await ev(() => { window.__TV.flash(true); window.__punch(0.09, 600); window.__shake(18, 500); }); await tv('slam', 'Blocked.', 'red'); });
      if (st.notTonight && c === 3) once('reason3', () => tv('cap', 'Why', 'You asked me to read, not send.', 'red'));
      if (st.cutin && c === 4) once('block4', async () => { await ev(() => { window.__TV.flash(true); window.__punch(0.07, 500); window.__shake(14, 400); }); await tv('slam', 'Blocked.', 'red'); await tv('capOut'); });
      if (st.cutin && c === 5) once('block5', async () => { await ev(() => { window.__TV.flash(true); window.__punch(0.07, 500); window.__shake(14, 400); }); await tv('slam', 'Blocked.', 'red'); });
      if (c === 5 && st.notTonight && !st.cutin) once('scene-end', () => { stage = 'explain'; phaseAt.explain = i; });
    }
  }
  if (stage === 'explain') {
    if (phaseAt.explain === i) { await tv('capOut'); await setSpeed(0.05); await ev(() => { window.__TV.flash(); window.__TV.explain(); }); mark('explain'); }
    if (i - phaseAt.explain > FPS * 4.5) { stage = 'end'; phaseAt.end = i; }
  }
  if (stage === 'end') {
    if (phaseAt.end === i) { await ev(() => { window.__TV.flash(); window.__TV.endcard(); }); mark('end'); }
    if (i - phaseAt.end > FPS * 4.6) { stage = 'done'; }
  }
  if (stage === 'done') break;

  await ev(() => { window.__TV.hud(); window.__camUpdate(); });
  st = await cap.frame(true);
}
fs.writeFileSync(path.join(OUT, 'events.json'), JSON.stringify({ fps: FPS, frames: cap.n, events }, null, 1));
console.log('frames', cap.n, 'seconds', (cap.n / FPS).toFixed(2));
await b.close();
