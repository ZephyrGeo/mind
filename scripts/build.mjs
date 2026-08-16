import { cp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";

const root = path.resolve(import.meta.dirname, "..");
const entryFile = path.join(root, "frontend", "app.js");
const outputDirectory = path.join(root, "dist");

async function fileExists(filePath) {
  try {
    await readFile(filePath);
    return true;
  } catch (error) {
    if (error?.code === "ENOENT" || error?.code === "EISDIR") {
      return false;
    }
    throw error;
  }
}

async function resolveAsFile(candidate) {
  for (const filePath of [candidate, `${candidate}.js`, path.join(candidate, "index.js")]) {
    if (await fileExists(filePath)) {
      return path.resolve(filePath);
    }
  }
  throw new Error(`Unable to resolve module: ${candidate}`);
}

function packageParts(specifier) {
  const parts = specifier.split("/");
  if (specifier.startsWith("@")) {
    return {
      packageName: parts.slice(0, 2).join("/"),
      subpath: parts.slice(2).join("/"),
    };
  }
  return { packageName: parts[0], subpath: parts.slice(1).join("/") };
}

function selectExport(exportsValue) {
  if (typeof exportsValue === "string") {
    return exportsValue;
  }
  if (exportsValue && typeof exportsValue === "object") {
    const browserValue = exportsValue.browser;
    if (typeof browserValue === "string") return browserValue;
    if (browserValue && typeof browserValue === "object") {
      if (typeof browserValue.require === "string") return browserValue.require;
      if (typeof browserValue.default === "string") return browserValue.default;
    }
    if (typeof exportsValue.require === "string") return exportsValue.require;
    if (typeof exportsValue.default === "string") return exportsValue.default;
    const nodeValue = exportsValue.node;
    if (nodeValue && typeof nodeValue === "object") {
      if (typeof nodeValue.require === "string") return nodeValue.require;
      if (typeof nodeValue.default === "string") return nodeValue.default;
    }
  }
  return undefined;
}

async function resolveSpecifier(specifier, importer) {
  if (specifier.startsWith(".")) {
    return resolveAsFile(path.resolve(path.dirname(importer), specifier));
  }

  const { packageName, subpath } = packageParts(specifier);
  const packageDirectory = path.join(root, "node_modules", packageName);
  const packageJson = JSON.parse(
    await readFile(path.join(packageDirectory, "package.json"), "utf8"),
  );
  const exportKey = subpath ? `./${subpath}` : ".";
  const exportedPath =
    selectExport(packageJson.exports?.[exportKey]) ??
    (subpath ? `./${subpath}.js` : packageJson.browser ?? packageJson.main ?? "index.js");

  return resolveAsFile(path.join(packageDirectory, exportedPath));
}

async function createBundle(entry) {
  const modules = new Map();
  const requirePattern = /require\(\s*["']([^"']+)["']\s*\)/g;

  async function visit(filePath) {
    const absolutePath = path.resolve(filePath);
    if (modules.has(absolutePath)) {
      return;
    }

    const source = await readFile(absolutePath, "utf8");
    const dependencyMap = {};
    const specifiers = [...source.matchAll(requirePattern)].map((match) => match[1]);

    modules.set(absolutePath, { source, dependencyMap });
    for (const specifier of new Set(specifiers)) {
      const dependencyPath = await resolveSpecifier(specifier, absolutePath);
      dependencyMap[specifier] = dependencyPath;
      await visit(dependencyPath);
    }
  }

  await visit(entry);

  const moduleIds = new Map(
    [...modules.keys()].map((modulePath, index) => [modulePath, String(index)]),
  );
  const serializedModules = [...modules.entries()]
    .map(([modulePath, definition]) => {
      const mappedDependencies = Object.fromEntries(
        Object.entries(definition.dependencyMap).map(([specifier, dependencyPath]) => [
          specifier,
          moduleIds.get(dependencyPath),
        ]),
      );
      return `${JSON.stringify(moduleIds.get(modulePath))}:[function(module,exports,require){\n${definition.source}\n},${JSON.stringify(mappedDependencies)}]`;
    })
    .join(",\n");

  return `/* Mind local React bundle. Third-party modules remain under their original licenses. */
(function(){
"use strict";
var process={env:{NODE_ENV:"production"}};
var __modules={${serializedModules}};
var __cache={};
function __require(id){
  if(__cache[id]) return __cache[id].exports;
  var tuple=__modules[id];
  if(!tuple) throw new Error("Unknown module "+id);
  var module={exports:{}};
  __cache[id]=module;
  function localRequire(specifier){
    var mapped=tuple[1][specifier];
    if(mapped===undefined) throw new Error("Unknown dependency "+specifier+" in "+id);
    return __require(mapped);
  }
  tuple[0](module,module.exports,localRequire);
  return module.exports;
}
__require(${JSON.stringify(moduleIds.get(path.resolve(entry)))});
})();\n`;
}

export async function build() {
  await rm(outputDirectory, { recursive: true, force: true });
  await mkdir(path.join(outputDirectory, "assets"), { recursive: true });

  const bundle = await createBundle(entryFile);
  await writeFile(path.join(outputDirectory, "assets", "app.js"), bundle);
  const runtimeConfig = {
    apiBase: process.env.MIND_PUBLIC_API_BASE ?? "http://127.0.0.1:8000",
    authProvider:
      process.env.MIND_PUBLIC_AUTH_PROVIDER ??
      process.env.MIND_AUTH_PROVIDER ??
      "local",
    requireVerifiedEmail:
      (process.env.MIND_PUBLIC_REQUIRE_VERIFIED_EMAIL ??
        process.env.MIND_REQUIRE_VERIFIED_EMAIL ??
        "0") === "1",
    firebaseAuthEmulatorUrl:
      process.env.MIND_PUBLIC_FIREBASE_AUTH_EMULATOR_URL ?? "",
    firebase: {
      apiKey: process.env.MIND_PUBLIC_FIREBASE_API_KEY ?? "",
      authDomain: process.env.MIND_PUBLIC_FIREBASE_AUTH_DOMAIN ?? "",
      projectId: process.env.MIND_PUBLIC_FIREBASE_PROJECT_ID ?? "",
      storageBucket: process.env.MIND_PUBLIC_FIREBASE_STORAGE_BUCKET ?? "",
      messagingSenderId:
        process.env.MIND_PUBLIC_FIREBASE_MESSAGING_SENDER_ID ?? "",
      appId: process.env.MIND_PUBLIC_FIREBASE_APP_ID ?? "",
    },
  };
  await writeFile(
    path.join(outputDirectory, "runtime-config.js"),
    `window.__MIND_CONFIG__=${JSON.stringify(runtimeConfig)};\n`,
  );
  await cp(
    path.join(root, "frontend", "index.html"),
    path.join(outputDirectory, "index.html"),
  );
  await cp(
    path.join(root, "frontend", "styles.css"),
    path.join(outputDirectory, "assets", "styles.css"),
  );

  const sizeInKb = Math.round(Buffer.byteLength(bundle) / 1024);
  console.log(`Built Mind web (${sizeInKb} KB).`);
}

if (import.meta.url === pathToFileURL(process.argv[1]).href) {
  await build();
}
