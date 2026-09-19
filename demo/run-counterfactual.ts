import { runCounterfactualCli } from "../packages/proxy/src/demo/runner.js";

runCounterfactualCli().catch((error: unknown) => {
  console.error(`[demo] ${error instanceof Error ? error.message : String(error)}`);
  process.exitCode = 1;
});
