import { spawn } from "node:child_process";

const children = [];
const pythonCommand = process.env.PYTHON ?? "python3";

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

start(pythonCommand, ["-m", "backend.app", "--port", "8000"], "api");
start(process.execPath, ["scripts/dev.mjs"], "web");

console.log("Starting Mind local workspace...");
