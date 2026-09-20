// Deterministic frame capture of live/index.html.
// The page's own clocks (performance.now, rAF, setTimeout/setInterval, CSS animations
// and transitions) are replaced by a manually advanced clock, so each output frame is
// exactly 1000/fps ms of page time regardless of how long the screenshot takes.
import puppeteer from 'puppeteer-core';
import fs from 'node:fs';
import path from 'node:path';

export const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';

const INJECT = `(()=>{
  let clock=0,tid=1,timers=[],raf=[];
  let s=0x9e3779b9;Math.random=()=>{s|=0;s=s+0x6D2B79F5|0;let t=Math.imul(s^s>>>15,1|s);t=t+Math.imul(t^t>>>7,61|t)^t;return((t^t>>>14)>>>0)/4294967296;};
  performance.now=()=>clock; Date.now=()=>1.75e12+clock;
  window.setTimeout=(fn,ms,...a)=>{const id=tid++;timers.push({id,at:clock+Math.max(0,+ms||0),fn,a,rep:0});return id;};
  window.setInterval=(fn,ms,...a)=>{const id=tid++;ms=Math.max(1,+ms||0);timers.push({id,at:clock+ms,fn,a,rep:ms});return id;};
  window.clearTimeout=window.clearInterval=id=>{timers=timers.filter(t=>t.id!==id);};
  window.requestAnimationFrame=cb=>{raf.push(cb);return raf.length;};
  const flush=()=>new Promise(r=>{const c=new MessageChannel();c.port1.onmessage=()=>r();c.port2.postMessage(0);});
  const seen=new WeakMap();
  function syncAnims(){for(const a of document.getAnimations()){let st=seen.get(a);if(!st){st={t0:clock};seen.set(a,st);a.pause();}a.currentTime=clock-st.t0;}}
  window.__clock=()=>clock;
  window.__tick=async(dt)=>{
    const end=clock+dt;
    for(;;){
      timers.sort((a,b)=>a.at-b.at);
      const t=timers[0]; if(!t||t.at>end)break;
      clock=Math.max(clock,t.at); timers.shift();
      if(t.rep){t.at+=t.rep;timers.push(t);}
      try{typeof t.fn==='function'&&t.fn(...t.a);}catch(e){console.error(e);}
      await flush();
    }
    clock=end;
    const cbs=raf;raf=[];
    for(const cb of cbs){try{cb(clock);}catch(e){console.error(e);}}
    await flush();
    syncAnims();
  };
})();`;

export async function launch() {
  return puppeteer.launch({
    executablePath: CHROME, headless: true,
    args: ['--no-sandbox', '--hide-scrollbars', '--font-render-hinting=none', '--force-color-profile=srgb', '--disable-lcd-text'],
  });
}

export class Capture {
  constructor(page, outDir, fps = 30, quality = 92) {
    this.page = page; this.outDir = outDir; this.fps = fps; this.n = 0; this.quality = quality;
    fs.mkdirSync(outDir, { recursive: true });
  }
  async openScene(url, css, extra) {
    const { page } = this;
    await page.evaluateOnNewDocument(INJECT);
    await page.setViewport({ width: 1280, height: 720, deviceScaleFactor: 1 });
    await page.goto(url, { waitUntil: 'load' });
    if (css) await page.addStyleTag({ content: css });
    if (extra) await page.evaluate(extra);
  }
  /** advance one frame; returns the state object from page-side `__state()` if defined */
  async frame(save = true) {
    const { page } = this;
    await page.evaluate((dt) => window.__tick(dt), 1000 / this.fps);
    const state = await page.evaluate(() => (window.__state ? window.__state() : null));
    if (save) {
      const f = path.join(this.outDir, `f_${String(this.n).padStart(5, '0')}.jpg`);
      await page.screenshot({ path: f, type: 'jpeg', quality: this.quality });
      this.n++;
    }
    return state;
  }
  async run(pred, maxFrames = 3000, save = true) { // frames until pred(state) true
    for (let i = 0; i < maxFrames; i++) { const st = await this.frame(save); if (pred(st)) return st; }
    throw new Error('run(): predicate not met in ' + maxFrames + ' frames');
  }
  async hold(seconds, save = true) { let st; for (let i = 0; i < Math.round(seconds * this.fps); i++) st = await this.frame(save); return st; }
}
