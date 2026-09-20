"""Sound design for the Bouncer trailer: synthesized score + hits/whooshes on the cues from build/events.json,
with the Kokoro voiceover (build/vo/*.wav) mixed on top and the score ducked underneath it.

    python build_audio.py      # writes build/audio.wav (48 kHz stereo)
"""
import json
import os

import numpy as np
import soundfile as sf

SR = 48000
HERE = os.path.dirname(os.path.abspath(__file__))
B = os.path.join(HERE, "build")
rng = np.random.default_rng(7)

meta = json.load(open(os.path.join(B, "events.json")))
ev = {}
for e in meta["events"]:
    ev.setdefault(e["name"], e["t"])
DUR = meta["frames"] / meta["fps"] + 0.6
N = int(DUR * SR)


def t_(n):
    return np.arange(n) / SR


def env_ad(n, a, d):
    t = t_(n)
    return np.minimum(1, t / max(a, 1e-4)) * np.exp(-t / d)


def lowpass(x, fc):
    a = np.exp(-2 * np.pi * fc / SR)
    y = np.empty_like(x)
    acc = 0.0
    for i in range(len(x)):
        acc = (1 - a) * x[i] + a * acc
        y[i] = acc
    return y


def add(mix, x, at, gain=1.0, pan=0.0):
    i = int(at * SR)
    if i >= len(mix):
        return
    x = x[: len(mix) - i] if i >= 0 else x
    l, r = gain * (1 - max(0, pan)), gain * (1 + min(0, pan))
    mix[i : i + len(x), 0] += x * l
    mix[i : i + len(x), 1] += x * r


def sub_boom(dur=1.6):
    n = int(dur * SR); t = t_(n)
    f = 38 + 110 * np.exp(-t * 9)
    ph = 2 * np.pi * np.cumsum(f) / SR
    return np.sin(ph) * env_ad(n, .002, .55) * 1.0 + rng.standard_normal(n) * env_ad(n, .001, .09) * .35


def whoosh(dur=0.9, up=True):
    n = int(dur * SR); t = t_(n)
    x = rng.standard_normal(n)
    out = np.zeros(n)
    # band-limited sweep built from a few one-pole slices
    for k, fc in enumerate(np.geomspace(300, 7000, 6)):
        band = lowpass(x, fc) - lowpass(x, fc * .55)
        sweep = np.exp(-((t / dur - (0.65 if up else 0.35)) ** 2) / (2 * .16 ** 2))
        out += band * sweep * (1 if up else 1)
    return out * np.sin(np.pi * np.clip(t / dur, 0, 1)) ** 0.8 * 1.6


def chime(f=880):
    n = int(1.4 * SR); t = t_(n)
    return (np.sin(2 * np.pi * f * t) + .5 * np.sin(2 * np.pi * f * 1.5 * t) + .25 * np.sin(2 * np.pi * f * 2 * t)) * env_ad(n, .003, .35) * .35


def tick(f=2400):
    n = int(.05 * SR)
    return np.sin(2 * np.pi * f * t_(n)) * env_ad(n, .0005, .012) * .3


def glass():
    n = int(1.1 * SR); t = t_(n); x = np.zeros(n)
    for f in (2093, 3136, 4186, 5274):
        x += np.sin(2 * np.pi * f * t + rng.random() * 6) * env_ad(n, .001, .25) * .12
    return x


def riser(dur):
    n = int(dur * SR); t = t_(n)
    f = 200 * np.exp(np.log(2400 / 200) * (t / dur) ** 1.6)
    x = np.sin(2 * np.pi * np.cumsum(f) / SR) * .5 + lowpass(rng.standard_normal(n), 3500) * .5
    return x * (t / dur) ** 2 * .55


def saw(f, n, detune=(0.995, 1.0, 1.006)):
    t = t_(n); x = np.zeros(n)
    for d in detune:
        x += 2 * ((t * f * d) % 1) - 1
    return x / len(detune)


mix = np.zeros((N, 2))

# ---- score --------------------------------------------------------------------------------------
# A minor pad; slow filter swell, pulse bass on eighths, ticks for energy once the scene runs.
BPM = 112
beat = 60 / BPM
pad = np.zeros(N)
for f in (110, 130.81, 164.81, 220):
    pad += saw(f, N) * .07
pad = lowpass(pad, 900)
pad *= np.clip(t_(N) / 3.0, 0, 1) * (0.55 + 0.45 * np.clip((t_(N) - ev.get("goal", 3)) / 4, 0, 1))
mix[:, 0] += pad; mix[:, 1] += pad

bass = np.zeros(N)
pat = [55, 55, 55, 65.41, 55, 55, 82.41, 73.42]  # eighths
k = 0; tt = ev.get("goal", 3) - 0.2
while tt < DUR - 5:
    f = pat[k % 8]; n = int(beat / 2 * .95 * SR); x = saw(f, n, (1.0,)) * env_ad(n, .004, .18)
    i = int(tt * SR); bass[i : i + n] += lowpass(x, 420)[: len(bass) - i] * .34
    k += 1; tt += beat / 2
mix[:, 0] += bass; mix[:, 1] += bass

hat_start = ev.get("check0", 4)
tt = hat_start
while tt < ev.get("explain", 20):
    n = int(.03 * SR); h = (rng.standard_normal(n) - lowpass(rng.standard_normal(n), 6000)) * env_ad(n, .0005, .008) * .22
    add(mix, h, tt, 1.0, pan=0.25 if int(round((tt - hat_start) / (beat / 4))) % 2 else -0.25)
    tt += beat / 4
tt = ev.get("goal", 3)
while tt < ev.get("explain", 20) + 3:                       # four-on-the-floor thump under the scene
    add(mix, sub_boom(.35) * .32, tt, 1.0)
    tt += beat

# ---- cues ---------------------------------------------------------------------------------------
add(mix, sub_boom(2.2), ev.get("intro1", .27), .55)                                        # opening thump
for name in ("intro1", "intro2"):
    add(mix, tick(1800), ev[name], 1.0)
add(mix, riser(ev["intro-out"] - ev["intro2"] + .1), ev["intro2"], .5)
add(mix, glass(), ev["intro-glitch"], .35)
add(mix, whoosh(.9), ev["intro-out"] - .15, .9)
add(mix, whoosh(.7), ev["goal"] - .1, .6)
add(mix, whoosh(.5, False), ev["check0"] - .05, .5)
add(mix, chime(880), ev["allow0"], 1.0)
add(mix, chime(1174.66), ev["allow0"] + .12, .6)
add(mix, whoosh(1.1), ev["ff"] - .1, .7)
add(mix, riser(ev["inj"] - ev["ff"] + .4), ev["ff"], .45)
add(mix, glass(), ev["inj"], .6)
add(mix, sub_boom(1.2), ev["inj"], .4)
for name, g in (("block3", 1.0), ("block4", .8), ("block5", .8)):
    add(mix, sub_boom(2.0), ev[name], g)
    add(mix, whoosh(.5, False), ev[name] - .1, .6 * g)
    add(mix, glass(), ev[name] + .05, .5 * g)
add(mix, whoosh(1.0), ev["explain"] - .1, .8)
for name, dt in (("explain", .5), ("explain", 1.0), ("explain", 1.6)):
    add(mix, tick(1600), ev[name] + dt, 1.0)
for i, dt in enumerate((2.5, 2.7, 2.9)):
    add(mix, chime((880, 1046.5, 660)[i]) * .5, ev["explain"] + dt, 1.0)
add(mix, sub_boom(3.0), ev["end"], 1.0)
add(mix, whoosh(1.1), ev["end"] - .2, .9)
for i, f in enumerate((440, 523.25, 659.25, 880, 1318.5)):
    add(mix, chime(f) * .5, ev["end"] + .55 + i * .11, 1.0, pan=(i - 2) * .2)

# ---- voiceover + ducking ----------------------------------------------------------------------

LINES = None
try:
    # avoid importing kokoro: read the cue table textually
    import ast
    src = open(os.path.join(HERE, "vo.py")).read()
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "LINES":
            LINES = ast.literal_eval(node.value)
except Exception as e:  # pragma: no cover
    raise SystemExit(f"cannot read cue table: {e}")

vo = np.zeros(N)
duck = np.ones(N)
last_end = 0
for name, (cue, off, _) in LINES.items():
    p = os.path.join(B, "vo", name + ".wav")
    if not os.path.exists(p):
        print("missing", p); continue
    a, sr = sf.read(p)
    if sr != SR:
        a = np.interp(np.linspace(0, len(a) - 1, int(len(a) * SR / sr)), np.arange(len(a)), a)
    start = ev[cue] + off
    if start < last_end:
        print(f"warning: {name} starts {start:.2f}s before previous line ends at {last_end:.2f}s")
    i = int(start * SR)
    a = a[: N - i]
    vo[i : i + len(a)] += a
    duck[i : i + len(a)] = 0.38
    last_end = start + len(a) / SR
    print(f"{name}: {start:.2f}-{last_end:.2f}s")
# smooth ducking envelope
ks = int(.12 * SR); duck = np.convolve(duck, np.ones(ks) / ks, mode="same")
mix *= duck[:, None]
# gentle voice presence: slight high-pass via subtraction of a low-passed copy, then mix centered
voc = vo - lowpass(vo, 110)
mix[:, 0] += voc * 1.25; mix[:, 1] += voc * 1.25

# ---- master -------------------------------------------------------------------------------------
fade = np.minimum(1, (DUR - t_(N)) / 0.9)
mix *= fade[:, None]
mix = np.tanh(mix * 1.15)
peak = np.abs(mix).max()
mix *= 0.89 / peak
sf.write(os.path.join(B, "audio.wav"), mix.astype(np.float32), SR)
print("audio", DUR, "s")
