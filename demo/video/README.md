# Demo video pipeline

Regenerates `demo/artifacts/bouncer-demo-v2.mp4` (1280x720, 30 fps, H.264 + AAC, macOS `say` narration, burned-in captions).

```bash
python3 demo/video/build_video.py                    # full rebuild, re-runs `npm run demo` (live Nemotron Super)
python3 demo/video/build_video.py --reuse-terminal   # reuse the last captured terminal output
python3 demo/video/build_video.py --skip-tts --skip-capture   # only re-encode / re-mix
```

Requirements: macOS, Google Chrome, ffmpeg, node, python3. The first run does `npm install` (puppeteer-core) in this folder.

## What it does
- `build_video.py` orchestrates everything and reads all numbers from `eval/results/*.json`
  (`go_no_go_noleak.json`, `go_no_go_v1.json`, `trajectory_offline.json`, and, when present,
  `trajectory_live.json` and `finetune/results/finetune_v1.json`). Nothing is hard-coded, so re-run it after new results land.
- Act 3 runs `cd packages/proxy && npm run demo -- --no-color` with the key passed only through the subprocess environment
  (key is read from `NVIDIA_API_KEY`, `$BOUNCER_ENV_FILE`, `<repo>/.env`, or `../bouncer/.env`; it is never printed or written).
  Output is scanned for the key and for `nvapi-` strings. If the live run fails, it falls back to `npm run demo:offline`
  and the captions say "offline replay with a scripted stand-in judge".
- `capture.mjs` + `scene_lib.mjs` drive `live/index.html` in headless Chrome with a fully virtual clock
  (performance.now, requestAnimationFrame, timers, CSS animations/transitions are stepped 1000/fps ms per frame),
  so capture is deterministic. Idle steps run at a higher `speed`. The scene is captioned as a scripted visualization, not a live model call.
- `cards.html` renders the title, terminal, evidence and closing cards.

Intermediate files go to `demo/video/build/` (safe to delete).
