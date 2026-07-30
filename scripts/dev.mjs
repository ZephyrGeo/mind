import { createReadStream, statSync, watch } from "node:fs";
import http from "node:http";
import path from "node:path";
import { build } from "./build.mjs";

const root = path.resolve(import.meta.dirname, "..");
const publicDirectory = path.join(root, "dist");
const port = Number(process.env.PORT ?? 3000);
const shouldWatch = !process.argv.includes("--no-watch");

const contentTypes = {
  ".css": "text/css; charset=utf-8",
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
};

await build();

const server = http.createServer((request, response) => {
  const requestedPath = decodeURIComponent(new URL(request.url, "http://localhost").pathname);
  const relativePath = requestedPath === "/" ? "index.html" : requestedPath.slice(1);
  let filePath = path.resolve(publicDirectory, relativePath);

  if (!filePath.startsWith(publicDirectory)) {
    response.writeHead(403).end("Forbidden");
    return;
  }

  try {
    if (!statSync(filePath).isFile()) {
      throw new Error("Not a file");
    }
  } catch {
    filePath = path.join(publicDirectory, "index.html");
  }

  response.writeHead(200, {
    "Cache-Control": "no-store",
    "Content-Type": contentTypes[path.extname(filePath)] ?? "application/octet-stream",
  });
  createReadStream(filePath).pipe(response);
});

server.listen(port, "127.0.0.1", () => {
  console.log(`Mind web is ready`);
  console.log(`Local: http://127.0.0.1:${port}/`);
});

if (shouldWatch) {
  let rebuildTimer;
  watch(path.join(root, "frontend"), { recursive: true }, () => {
    clearTimeout(rebuildTimer);
    rebuildTimer = setTimeout(async () => {
      try {
        await build();
        console.log("Web changes rebuilt. Refresh the page to view them.");
      } catch (error) {
        console.error("Web rebuild failed:", error.message);
      }
    }, 120);
  });
}
