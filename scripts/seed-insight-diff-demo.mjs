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
  [path.join(root, "scripts", "seed_insight_diff_demo.py")],
  { cwd: root, stdio: "inherit" },
);

process.exit(result.status ?? 1);
