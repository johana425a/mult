import fs from "node:fs";
import path from "node:path";

function listJsonFiles(dir) {
  const out = [];
  for (const ent of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, ent.name);
    if (ent.isDirectory()) out.push(...listJsonFiles(full));
    else if (ent.isFile() && ent.name.endsWith(".json")) out.push(full);
  }
  return out;
}

function loadJson(p) {
  return JSON.parse(fs.readFileSync(p, "utf8"));
}

const webRoot = path.resolve(process.cwd());
const localesRoot = path.join(webRoot, "locales");
const enRoot = path.join(localesRoot, "en");

if (!fs.existsSync(enRoot)) {
  console.error("[i18n:parity] The canonical English catalog is missing.");
  process.exit(2);
}

const enFiles = listJsonFiles(enRoot).sort();
if (!enFiles.length) throw new Error("The English catalog contains no translation files.");
for (const file of enFiles) {
  const catalog = loadJson(file);
  if (!catalog || typeof catalog !== "object" || Array.isArray(catalog)) {
    throw new Error(`Invalid English catalog: ${path.relative(enRoot, file)}`);
  }
}
console.log(`[i18n:parity] OK: ${enFiles.length} canonical English catalog files`);
