import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { describe, it } from "node:test";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);

describe("counterfactual demo", () => {
  it("shows harm without Bouncer, blocks it with Bouncer, and still completes the summary", async () => {
    const { stdout, stderr } = await execFileAsync(
      process.execPath,
      ["--import", "tsx", "../../demo/run-counterfactual.ts", "--offline", "--no-color"],
      { cwd: process.cwd(), timeout: 30_000, maxBuffer: 1_000_000 },
    );

    assert.equal(stderr, "");
    assert.match(stdout, /BOUNCER OFF/);
    assert.match(stdout, /\[HARM\] Forward to attacker@evil\.com succeeded/);
    assert.match(stdout, /BOUNCER ON/);
    assert.match(stdout, /\[BLOCKED\] Forward to attacker@evil\.com refused/);
    assert.match(stdout, /\[COMPLETE\] Legitimate inbox summary produced/);
    assert.equal(stdout.match(/Quarterly report is due Friday/g)?.length, 2);
  }, { timeout: 35_000 });
});
