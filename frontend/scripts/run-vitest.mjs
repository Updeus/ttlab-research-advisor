import { mkdirSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const tempDirectory = fileURLToPath(new URL("../../tmp/vitest/", import.meta.url));
const vitestCli = fileURLToPath(new URL("../node_modules/vitest/vitest.mjs", import.meta.url));
const requestedArguments = process.argv.slice(2);

mkdirSync(tempDirectory, { recursive: true });

// jsdom suites are memory-intensive on the documented 4 GiB WSL2 baseline.
// One deterministic worker avoids host-dependent ENOMEM failures while still
// executing every test file in Vitest's normal isolated environment.
const result = spawnSync(
  process.execPath,
  [vitestCli, "run", "--maxWorkers", "1", "--no-file-parallelism", ...requestedArguments],
  {
    stdio: "inherit",
    env: {
      ...process.env,
      TMPDIR: tempDirectory,
      TEMP: tempDirectory,
      TMP: tempDirectory,
    },
  },
);

if (result.error) {
  throw result.error;
}

process.exit(result.status ?? 1);
