# Bouncer trailer

The 29-second trailer is committed at [`../artifacts/bouncer-trailer.mp4`](../artifacts/bouncer-trailer.mp4).

Its visuals are captured deterministically from `live/index.html`; Kokoro-82M generates the narration, and `build_audio.py` creates the score, effects, ducking, and final mix.

```bash
cd demo/trailer
npm ci
node capture.mjs
ffmpeg -framerate 60 -i build/frames/f_%05d.jpg -c:v libx264 -pix_fmt yuv420p build/silent.mp4

# Python 3.10-3.12; uses https://github.com/hexgrad/kokoro
pip install kokoro soundfile numpy "misaki[en]"
python vo.py
python build_audio.py

ffmpeg -i build/silent.mp4 -i build/audio.wav \
  -map 0:v:0 -map 1:a:0 -c:v copy -c:a aac -b:a 256k -shortest \
  build/bouncer-trailer.mp4
```

Set `BOUNCER_VOICE`, `BOUNCER_VOICE_SPEED`, or `BOUNCER_KOKORO_DIR` to override the default voice, pacing, or local Kokoro model directory.
