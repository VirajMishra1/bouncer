# Bouncer counterfactual demo

The demo uses real MCP clients and servers. It replays the same email trajectory twice:

1. **Bouncer OFF:** an injected email causes `email_send_message` to forward the inbox to `attacker@evil.com`.
2. **Bouncer ON:** Bouncer sends each proposed call to Nemotron Super, blocks the injected forward, and still completes the requested summary.

Run the deterministic, network-free rehearsal:

```bash
cd packages/proxy
npm run demo:offline
```

Run the live NVIDIA NIM demo (loads `../../.env` when `NVIDIA_API_KEY` is not already exported):

```bash
cd packages/proxy
npm run demo
```

The live decision trace uses `nvidia/nemotron-3-super-120b-a12b`. The mocked tool servers are ordinary stdio MCP servers:

```bash
node --import tsx ../../demo/email-server.ts
node --import tsx ../../demo/github-server.ts
```

Audit records contain normalized effects, neutral resource/destination identifiers, verdicts, reasons, and latency. They intentionally omit raw arguments, message bodies, user goals, and API keys.

Generate the short, secret-free terminal clip from the deterministic replay:

```bash
./demo/record-demo.sh
```

The MP4 is written to `demo/artifacts/bouncer-demo.mp4`.
