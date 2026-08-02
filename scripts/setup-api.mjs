import { existsSync } from "node:fs";
import { spawnSync } from "node:child_process";
import path from "node:path";

const root = path.resolve(import.meta.dirname, "..");
const configuredPython = process.env.PYTHON;
const candidates = configuredPython
  ? [configuredPython]
  : ["python3.12", "python3.11", "python3.10", "python3"];

function run(command, args, options = {}) {
  const result = spawnSync(command, args, {
    cwd: root,
    encoding: "utf8",
    stdio: options.capture ? "pipe" : "inherit",
  });
  return result;
}

function selectPython() {
  for (const candidate of candidates) {
    const result = run(
      candidate,
      [
        "-c",
        "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')",
      ],
      { capture: true },
    );
    if (result.status !== 0) continue;
    const [major, minor] = result.stdout.trim().split(".").map(Number);
    if (major === 3 && minor >= 10) return candidate;
  }
  throw new Error(
    "Mind requires Python 3.10 or newer. Install Python 3.12, or set PYTHON to a compatible executable.",
  );
}

const python = selectPython();
const venvDirectory = path.join(root, ".venv");
const venvPython =
  process.platform === "win32"
    ? path.join(venvDirectory, "Scripts", "python.exe")
    : path.join(venvDirectory, "bin", "python");

if (!existsSync(venvPython)) {
  console.log(`Creating .venv with ${python}...`);
  const createResult = run(python, ["-m", "venv", ".venv"]);
  if (createResult.status !== 0) process.exit(createResult.status ?? 1);
}

console.log("Installing locked API dependencies...");
const installResult = run(venvPython, [
  "-m",
  "pip",
  "install",
  "--requirement",
  "requirements.lock",
]);
if (installResult.status !== 0) process.exit(installResult.status ?? 1);

console.log("Mind API environment is ready.");

