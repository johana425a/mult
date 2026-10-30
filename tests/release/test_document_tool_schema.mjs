// Compile the shipped definition with the pinned Harness DSL, not a JSON Schema mock.
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { resolve, dirname } from 'node:path';
import vm from 'node:vm';
import { runReaderProcess } from '../../integration/harness/documents.mjs';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
const dependency = process.env.DEEPSTEAM_HARNESS_TEST_DEPENDENCIES;
assert.ok(dependency, 'Set DEEPSTEAM_HARNESS_TEST_DEPENDENCIES to the frozen runtime package.json');
const require = createRequire(dependency);
const { defineTool } = await import(pathToFileURL(require.resolve('@deepseek-ai/dsh-tools')));
const source = readFileSync(resolve(root, 'integration/harness/workspaces.mjs'), 'utf8');
const match = source.match(/const documentParameters = (\{[\s\S]*?\n  \});/);
assert.ok(match, 'The reader definition must be compiled before host startup');
const parameters = vm.runInNewContext('(' + match[1] + ')');
const tool = defineTool({ name: 'read_document', description: 'Reader schema compatibility', parameters,
  output: { schema: { type: 'json' }, render: () => [] }, execute: async args => args });
assert.equal(tool.parameters.properties.max_units.type, 'integer');
assert.ok(tool.parameters.required.includes('path'));
await assert.rejects(() => tool.execute({path: 'sample.pdf', max_units: 'bad'}, {}), /invalid arguments/);
assert.equal((await tool.execute({path: 'sample.pdf', max_units: 10}, {})).max_units, 10);

// Exercise the real child process environment rather than inspecting source text.
const python = resolve(dirname(dependency), '../python/python.exe');
const previousLimit = process.env.EDUAGENT_DOCUMENT_MAX_BYTES;
try {
  for (const [raw, mib] of [[undefined, 512], ['invalid', 512], ['1073741824', 512], ['104857600', 100], ['0', 1]]) {
    if (raw === undefined) delete process.env.EDUAGENT_DOCUMENT_MAX_BYTES;
    else process.env.EDUAGENT_DOCUMENT_MAX_BYTES = raw;
    const value = await runReaderProcess(python, ['-c', 'import os,json;print(json.dumps({"limit":int(os.environ["EDUAGENT_DOCUMENT_MAX_BYTES"])}))']);
    assert.equal(value.limit, mib * 1024 * 1024);
  }
} finally {
  if (previousLimit === undefined) delete process.env.EDUAGENT_DOCUMENT_MAX_BYTES;
  else process.env.EDUAGENT_DOCUMENT_MAX_BYTES = previousLimit;
}
