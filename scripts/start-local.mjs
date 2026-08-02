import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";

const children = [];
const root = path.resolve(import.meta.dirname, "..");
const venvPython =
  process.platform === "win32"
    ? path.join(root, ".venv", "Scripts", "python.exe")
    : path.join(root, ".venv", "bin", "python");
const venvServer =
  process.platform === "win32"
    ? path.join(root, ".venv", "Scripts", "uvicorn.exe")
    : path.join(root, ".venv", "bin", "uvicorn");
const pythonCommand =
  process.env.PYTHON ?? (existsSync(venvServer) ? venvPython : "python3");

function start(command, args, label) {
  const child = spawn(command, args, {
    cwd: process.cwd(),
    env: process.env,
    stdio: ["ignore", "pipe", "pipe"],
  });
  children.push(child);

  child.stdout.on("data", (chunk) => process.stdout.write(`[${label}] ${chunk}`));
  child.stderr.on("data", (chunk) => process.stderr.write(`[${label}] ${chunk}`));
  child.on("exit", (code) => {
    if (code && code !== 0) {
      console.error(`${label} stopped with code ${code}.`);
    }
  });
}

function shutdown() {
  for (const child of children) {
    child.kill("SIGTERM");
  }
  setTimeout(() => process.exit(0), 200);
}

process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);

start(
  pythonCommand,
  [
    "-m",
    "backend.app",
    "--host",
    process.env.MIND_API_HOST ?? "127.0.0.1",
    "--port",
    process.env.MIND_API_PORT ?? "8000",
  ],
  "api",
);
start(process.execPath, ["scripts/dev.mjs"], "web");

console.log("Starting Mind local workspace...");
