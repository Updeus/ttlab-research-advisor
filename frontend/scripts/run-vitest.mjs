import { mkdirSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const tempDirectory = fileURLToPath(new URL("../../tmp/vitest/", import.meta.url));
const vitestCli = fileURLToPath(new URL("../node_modules/vitest/vitest.mjs", import.meta.url));

mkdirSync(tempDirectory, { recursive: true });

const result = spawnSync(process.execPath, [vitestCli, "run", ...process.argv.slice(2)], {
  stdio: "inherit",
  env: {
    ...process.env,
    TMPDIR: tempDirectory,
    TEMP: tempDirectory,
    TMP: tempDirectory,
  },
});

if (result.error) {
  throw result.error;
}

process.exit(result.status ?? 1);
