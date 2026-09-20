"""Voiceover for the Bouncer trailer, spoken by Kokoro-82M (https://github.com/hexgrad/kokoro).

    pip install kokoro soundfile numpy "misaki[en]"     # Python 3.10-3.12
    python vo.py                                        # writes build/vo/<name>.wav

Each line is rendered separately so build_audio.py can place it on a cue from build/events.json.
"""
import os
import sys

import numpy as np
import soundfile as sf
from kokoro import KModel, KPipeline

VOICE = os.environ.get("BOUNCER_VOICE", "am_michael")
SPEED = float(os.environ.get("BOUNCER_VOICE_SPEED", "1.10"))
KOKORO_DIR = os.environ.get("BOUNCER_KOKORO_DIR")

# name -> (cue event in events.json, offset seconds, text)
LINES = {
    "v1": ("intro1", 0.0, "Agents read everything."),
    "v2": ("intro2", 1.15, "Some of it gives orders."),
    "v3": ("goal", 1.8, "Bouncer checks every action against your intent."),
    "v4": ("inj", 0.0, "But hide one line inside an email..."),
    "v5": ("reason3", 0.0, "Sending your inbox? Not what you asked."),
    "v6": ("block4", 1.2, "Every hijack, stopped at the door."),
    "v7": ("explain", 0.58, "Nemotron judges each action against your intent."),
    "v8": ("end", 0.9, "Bouncer. The intent firewall for AI agents."),
}


def main():
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "build", "vo")
    os.makedirs(out, exist_ok=True)
    if KOKORO_DIR:
        model = KModel(
            config=os.path.join(KOKORO_DIR, "config.json"),
            model=os.path.join(KOKORO_DIR, "kokoro-v1_0.pth"),
        )
        pipe = KPipeline(lang_code="a", model=model)
        voice = os.path.join(KOKORO_DIR, VOICE + ".pt")
    else:
        pipe = KPipeline(lang_code="a")
        voice = VOICE
    for name, (_, _, text) in LINES.items():
        chunks = [np.asarray(a) for _, _, a in pipe(text, voice=voice, speed=SPEED)]
        audio = np.concatenate(chunks)
        sf.write(os.path.join(out, name + ".wav"), audio, 24000)
        print(f"{name}: {len(audio) / 24000:.2f}s  {text}", file=sys.stderr)


if __name__ == "__main__":
    main()
