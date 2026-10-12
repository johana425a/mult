/** File-backed source coverage survives context compaction and task restarts. */
import { mkdir, readFile, writeFile, rename } from 'node:fs/promises';
import { join } from 'node:path';
import { createHash, randomUUID } from 'node:crypto';

export async function createTaskLedger(profile) {
  const root = join(profile, 'source-ledgers');
  await mkdir(root, { recursive: true });
  const cache = new Map(); const writes = new Map();
  function pathFor(id) { return join(root, createHash('sha256').update(id).digest('hex') + '.json'); }
  async function load(id) {
    if (!cache.has(id)) {
      let value;
      try { value = JSON.parse(await readFile(pathFor(id), 'utf8')); }
      catch (cause) { if (cause.code !== 'ENOENT') throw cause; }
      cache.set(id, value ?? { schema: 1, session_id: id, manifest_complete: false, sources: {}, summary: '', next_steps: [] });
    }
    return cache.get(id);
  }
  async function save(id, ledger) {
    ledger.updated_at = new Date().toISOString();
    const content = JSON.stringify(ledger);
    const previous = writes.get(id) ?? Promise.resolve();
    const job = previous.then(async () => {
      const path = pathFor(id); const temporary = path + '.' + randomUUID() + '.tmp';
      await writeFile(temporary, content, 'utf8'); await rename(temporary, path);
    });
    writes.set(id, job.catch(() => {})); await job;
  }
  function summary(ledger, offset = 0, limit = 30) {
    const sources = Object.values(ledger.sources);
    const completed = sources.filter(source => source.complete).length;
    const unsupported = sources.filter(source => source.supported === false).length;
    const rows = sources.slice(offset, offset + limit).map(({ delivered_units, units, pending_units, source_summary, output_references, ...source }) => ({
      ...source, delivered_unit_count: Object.values(delivered_units ?? {}).filter(unit => unit.delivered).length,
      pending_unit_count: pending_units?.length ?? null, pending_units_preview: pending_units?.slice(0, 10) ?? [],
      has_saved_summary: Boolean(source_summary), output_reference_count: output_references?.length ?? 0,
      detail_tool: 'read_task_progress(source_path=path)' }));
    return { summary: ledger.summary, next_steps: ledger.next_steps, manifest_complete: ledger.manifest_complete,
      coverage: { source_count: sources.length, complete_count: completed, unsupported_count: unsupported,
        scope: 'tool_result_delivery', semantic_completeness: 'not_guaranteed',
        pending_count: sources.length - completed - unsupported,
        excluded_entries: ledger.excluded_entries ?? 0, unavailable_entries: ledger.unavailable_entries ?? 0,
        skipped_entries: ledger.skipped_entries ?? 0,
        reading_complete: ledger.manifest_complete && sources.length === completed && !(ledger.unavailable_entries > 0) },
      sources: rows, offset, next_offset: offset + rows.length < sources.length ? offset + rows.length : null };
  }
  return {
    async recordDocument(id, requestedPath, result) {
      if (!result?.ok) return;
      const ledger = await load(id);
      const key = String(requestedPath).replaceAll('\\', '/').replace(/^\.\//, '');
      const digest = result.document?.sha256;
      let source = ledger.sources[key];
      if (!source || digest && source.sha256 && digest !== source.sha256) source = { path: key, units: [], complete: false };
      source.sha256 = digest ?? source.sha256;
      source.unit_count = result.document?.unit_count ?? source.unit_count;
      source.delivered_units ??= {};
      for (const unit of result.units ?? []) {
        if (!Number.isInteger(unit.unit_index) || unit.unit_index < 1) continue;
        const unitKey = String(unit.unit_index), old = source.delivered_units[unitKey];
        const total = unit.total_chars;
        const start = unit.char_start, end = unit.char_end;
        if (![total, start, end].every(Number.isInteger) || start < 0 || end < start || end > total) continue;
        const sameText = old && old.text_hash === unit.unit_text_sha256 && old.total_chars === total;
        const spans = [...(sameText ? old.spans : []), [start, end]].sort((a, b) => a[0] - b[0]);
        const merged = [];
        for (const span of spans) {
          const last = merged.at(-1);
          if (last && span[0] <= last[1]) last[1] = Math.max(last[1], span[1]);
          else merged.push([...span]);
        }
        source.delivered_units[unitKey] = { unit_index: unit.unit_index, locator: unit.locator,
          text_hash: unit.unit_text_sha256, total_chars: total, spans: merged,
          delivered: merged.length === 1 && merged[0][0] === 0 && merged[0][1] === total,
          unresolved: unit.coverage?.unresolved ?? [], visual_review_required: unit.coverage?.visual_review_required === true };
      }
      const locators = (result.units ?? []).map(unit => unit.locator).filter(Boolean);
      source.units = [...new Map([...source.units, ...locators].map(locator => [JSON.stringify(locator), locator])).values()];
      source.next_cursor = result.next_cursor ?? result.pagination?.next_cursor ?? null;
      // Exhausting one arbitrary requested range does not imply the whole file.
      // Only parser-owned coverage metadata can certify whole-document coverage.
      source.coverage = result.coverage ?? source.coverage;
      // Only tool-returned ranges count. Extraction in another conversation or
      // an exhausted last-page cursor cannot mark this task's source as read.
      source.complete = Number.isInteger(source.unit_count) && source.unit_count >= 0
        && Object.values(source.delivered_units).filter(unit => unit.delivered).length === source.unit_count;
      source.semantic_completeness = 'not_guaranteed';
      source.pending_units = Number.isInteger(source.unit_count)
        ? Array.from({ length: source.unit_count }, (_, i) => i + 1).filter(i => !source.delivered_units[i]?.delivered) : [];
      source.status = result.status ?? 'read';
      source.engine = result.engine ?? result.parser?.engine ?? source.engine;
      ledger.sources[key] = source; await save(id, ledger);
    },
    async manifest(id, entries, complete, cursor = null, metadata = {}) {
      const ledger = await load(id);
      for (const entry of entries) {
        if (!entry.path || entry.kind === 'directory' || entry.type === 'directory') continue;
        const key = entry.path.replaceAll('\\', '/').replace(/^\.\//, '');
        const prior = ledger.sources[key];
        if (!prior || prior.mtime_ns != null && entry.mtime_ns != null &&
          (prior.mtime_ns !== entry.mtime_ns || prior.bytes !== entry.bytes)) {
          ledger.sources[key] = { path: key, units: [], complete: false, status: 'pending' };
        }
        Object.assign(ledger.sources[key], { supported: entry.supported, bytes: entry.bytes, mtime_ns: entry.mtime_ns });
        if (entry.supported === false) ledger.sources[key].status = 'unsupported';
      }
      ledger.manifest_complete = complete; ledger.manifest_cursor = cursor;
      for (const key of ['skipped_entries', 'excluded_entries', 'unavailable_entries']) {
        if (Number.isInteger(metadata[key]) && metadata[key] >= 0) ledger[key] = metadata[key];
      }
      await save(id, ledger); return summary(ledger);
    },
    async update(id, input) {
      const ledger = await load(id);
      const invalid = () => Object.assign(new Error('Progress is too large or malformed. Save per-source notes with source_path/source_summary and store full outputs in task files; no existing progress was changed.'), { code: 'task_progress_size_limit' });
      if (input.summary !== undefined && (typeof input.summary !== 'string' || input.summary.length > 12000)) throw invalid();
      if (input.next_steps !== undefined && (!Array.isArray(input.next_steps) || input.next_steps.length > 100
        || input.next_steps.some(value => typeof value !== 'string' || value.length > 1000))) throw invalid();
      if (input.source_path !== undefined && (typeof input.source_path !== 'string' || !ledger.sources[input.source_path])) throw invalid();
      if (input.source_summary !== undefined && (!input.source_path || typeof input.source_summary !== 'string' || input.source_summary.length > 24000)) throw invalid();
      if (input.output_references !== undefined && (!input.source_path || !Array.isArray(input.output_references) || input.output_references.length > 100
        || input.output_references.some(value => typeof value !== 'string' || value.length > 2000))) throw invalid();
      if (typeof input.summary === 'string') ledger.summary = input.summary;
      if (input.next_steps) ledger.next_steps = [...input.next_steps];
      if (input.source_path) {
        const source = ledger.sources[input.source_path];
        if (input.source_summary !== undefined) source.source_summary = input.source_summary;
        if (input.output_references !== undefined) source.output_references = [...input.output_references];
        source.notes_provenance = 'task_summary_not_independent_verification';
      }
      await save(id, ledger); return summary(ledger);
    },
    async read(id, offset = 0, limit = 30) { return summary(await load(id), offset, Math.min(100, Math.max(1, limit))); },
    async source(id, path, offset = 0, limit = 30) {
      const ledger = await load(id), source = ledger.sources[path];
      if (!source) return { found: false, path };
      const count = source.unit_count ?? 0, end = Math.min(count, offset + Math.min(100, Math.max(1, limit)));
      return { found: true, path, unit_count: count, complete: source.complete,
        source_summary: source.source_summary ?? '', output_references: source.output_references ?? [],
        notes_provenance: source.notes_provenance,
        units: Array.from({ length: Math.max(0, end - offset) }, (_, i) => source.delivered_units?.[offset + i + 1]
          ?? { unit_index: offset + i + 1, delivered: false, spans: [] }),
        offset, next_offset: end < count ? end : null, next_cursor: source.next_cursor };
    },
    async context(id) {
      const state = summary(await load(id), 0, 8);
      return `Persistent task source ledger (read_task_progress for remaining source pages):\n${JSON.stringify(state)}`;
    },
  };
}
