import { existsSync } from "node:fs";
import { spawnSync } from "node:child_process";
import path from "node:path";

const root = path.resolve(import.meta.dirname, "..");
const venvPython =
  process.platform === "win32"
    ? path.join(root, ".venv", "Scripts", "python.exe")
    : path.join(root, ".venv", "bin", "python");
const python = process.env.PYTHON ?? (existsSync(venvPython) ? venvPython : "python3");
const result = spawnSync(
  python,
  ["-m", "unittest", "discover", "-s", "backend/tests", "-v"],
  { cwd: root, stdio: "inherit" },
);

process.exit(result.status ?? 1);

