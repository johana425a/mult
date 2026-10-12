/** Verify syntax and English source defaults without installing dependencies. */
const fs = require('node:fs');
const path = require('node:path');
const [repoRoot, baselineRoot, typescriptPath, reportPath, exclusionsPath] = process.argv.slice(2);
if (!repoRoot || !baselineRoot || !typescriptPath || !reportPath || !exclusionsPath) {
  throw new Error('Expected repository, baseline, TypeScript, report and exclusions paths');
}
const ts = require(typescriptPath);
const cjk = /[\u3400-\u9fff]/u;
const scopes = ['packages/client', 'apps'];
const textExtensions = new Set(['.ts', '.tsx', '.js', '.mjs', '.cjs', '.css', '.json', '.yaml', '.yml', '.md', '.html', '.nsh', '.nsi', '.txt']);
const artwork = new Set([
  'packages/client/ui-settings-account/src/client/assets/onboarding-recharge-zh-dark.png',
  'packages/client/ui-settings-account/src/client/assets/onboarding-recharge-zh.png',
  'packages/client/ui-settings-account/src/client/assets/onboarding-welcome-zh-dark.png',
  'packages/client/ui-settings-account/src/client/assets/onboarding-welcome-zh.png',
]);
function walk(directory) {
  return fs.readdirSync(directory, { withFileTypes: true }).flatMap(entry => {
    const name = path.join(directory, entry.name);
    return entry.isDirectory() ? walk(name) : [name];
  });
}
const excluded = [];
const diagnostics = [];
const activeCjk = [];
const invalidJson = [];
const newlyUnusedImports = [];
let syntaxFiles = 0;
let changedSyntaxFiles = 0;
let textFiles = 0;
for (const scope of scopes) {
  for (const filename of walk(path.join(repoRoot, scope))) {
    const relative = path.relative(repoRoot, filename).split(path.sep).join('/');
    if (relative.split('/').some(part => part === 'tests' || part === 'stress-tests') || artwork.has(relative)) {
      excluded.push(relative);
      continue;
    }
    const extension = path.extname(filename);
    if (!textExtensions.has(extension)) continue;
    const text = fs.readFileSync(filename, 'utf8');
    textFiles += 1;
    if (cjk.test(relative) || cjk.test(text)) activeCjk.push(relative);
    if (extension === '.json') {
      try {
        if (path.basename(filename).startsWith('tsconfig')) {
          const parsed = ts.parseConfigFileTextToJson(filename, text);
          if (parsed.error) throw new Error(ts.flattenDiagnosticMessageText(parsed.error.messageText, '\n'));
        } else JSON.parse(text);
      } catch (error) { invalidJson.push({ path: relative, error: error.message }); }
    }
    if (extension !== '.ts' && extension !== '.tsx') continue;
    syntaxFiles += 1;
    const source = ts.createSourceFile(filename, text, ts.ScriptTarget.Latest, false,
      extension === '.tsx' ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
    const originalFile = path.join(baselineRoot, relative);
    const original = fs.existsSync(originalFile) ? fs.readFileSync(originalFile, 'utf8') : undefined;
    if (original !== text) changedSyntaxFiles += 1;
    if (original !== text) {
      const counts = new Map();
      const importNames = [];
      function inspect(node) {
        if (ts.isIdentifier(node)) counts.set(node.text, (counts.get(node.text) ?? 0) + 1);
        if (ts.isImportDeclaration(node) && node.importClause) {
          if (node.importClause.name) importNames.push(node.importClause.name.text);
          const bindings = node.importClause.namedBindings;
          if (bindings && ts.isNamedImports(bindings)) {
            for (const entry of bindings.elements) importNames.push(entry.name.text);
          } else if (bindings && ts.isNamespaceImport(bindings)) importNames.push(bindings.name.text);
        }
        ts.forEachChild(node, inspect);
      }
      inspect(source);
      for (const name of importNames) {
        if (counts.get(name) === 1) newlyUnusedImports.push({ path: relative, name });
      }
    }
    const originalDiagnostics = original === undefined ? [] : ts.createSourceFile(
      originalFile, original, ts.ScriptTarget.Latest, false,
      extension === '.tsx' ? ts.ScriptKind.TSX : ts.ScriptKind.TS,
    ).parseDiagnostics;
    const baselineCodes = new Set(originalDiagnostics.map(d => d.code));
    for (const diagnostic of source.parseDiagnostics) {
      diagnostics.push({ path: relative, code: diagnostic.code,
        existingInBaseline: baselineCodes.has(diagnostic.code),
        message: ts.flattenDiagnosticMessageText(diagnostic.messageText, '\n') });
    }
  }
}
const localeSource = fs.readFileSync(path.join(repoRoot, 'packages/client/locale/src/client/index.ts'), 'utf8');
const desktopSource = fs.readFileSync(path.join(repoRoot, 'apps/desktop/src/locale.ts'), 'utf8');
const checks = {
  activeTextContainsNoCjk: activeCjk.length === 0,
  jsonParses: invalidJson.length === 0,
  noNewSyntaxErrors: diagnostics.every(d => d.existingInBaseline),
  englishOnlyBuiltInSelector: localeSource.includes("LOCALE_IDS.filter(id => id === 'en')"),
  browserStartsInEnglish: /function resolveInitialLocale[^]*?return FALLBACK_LOCALE/.test(localeSource),
  desktopStartsInEnglish: /function resolveDesktopLocale[^]*?return \{ id: 'en', messages: en \}/.test(desktopSource),
  changedImportsStillReferenced: newlyUnusedImports.length === 0,
};
const report = { passed: Object.values(checks).every(Boolean), syntaxFiles, changedSyntaxFiles, textFiles,
  checks, diagnostics, invalidJson, activeCjk, newlyUnusedImports, excludedFiles: excluded.length,
  limits: ['Dependency type checking and interactive UI tests are not part of this syntax-only check.'] };
fs.writeFileSync(reportPath, JSON.stringify(report, null, 2) + '\n');
fs.writeFileSync(exclusionsPath, JSON.stringify({ paths: excluded.sort(), reason: 'Legacy multilingual tests and unused translated onboarding artwork' }, null, 2) + '\n');
console.log(JSON.stringify(report));
if (!report.passed) process.exitCode = 1;
