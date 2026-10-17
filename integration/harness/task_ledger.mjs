/** File-backed source coverage survives context compaction and task restarts. */
import { mkdir, readFile, writeFile, rename } from 'node:fs/promises';
import { join } from 'node:path';
import { createHash, randomUUID } from 'node:crypto';

export async function createTaskLedger(profile, options = {}) {
  const root = join(profile, 'source-ledgers');
  await mkdir(root, { recursive: true });
  const cache = new Map(); const writes = new Map(); const loads = new Map(); const operations = new Map();
  function pathFor(id) { return join(root, createHash('sha256').update(id).digest('hex') + '.json'); }
  async function load(id) {
    if (!cache.has(id) && !loads.has(id)) loads.set(id, (async () => {
      let value;
      try { value = JSON.parse(await readFile(pathFor(id), 'utf8')); }
      catch (cause) { if (cause.code !== 'ENOENT') throw cause; }
      cache.set(id, value ?? { schema: 1, session_id: id, manifest_complete: false, sources: {}, summary: '', next_steps: [] });
    })().finally(() => loads.delete(id)));
    if (loads.has(id)) await loads.get(id);
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
  const normalized = path => String(path).replaceAll('\\','/').replace(/^\.\//,'');
  function mergeEvidence(target, prior) {
    target.units=[...new Map([...(target.units||[]),...(prior.units||[])].map(unit=>[JSON.stringify(unit),unit])).values()];
    target.delivered_units ??= {};
    for(const [index,unit] of Object.entries(prior.delivered_units||{})) {
      const current=target.delivered_units[index];
      if(!current){target.delivered_units[index]=unit;continue;}
      if(current.text_hash!==unit.text_hash||current.total_chars!==unit.total_chars)continue;
      const spans=[...current.spans,...unit.spans].sort((a,b)=>a[0]-b[0]), merged=[];
      for(const span of spans){const last=merged.at(-1);if(last&&span[0]<=last[1])last[1]=Math.max(last[1],span[1]);else merged.push([...span]);}
      current.spans=merged;current.delivered=merged.length===1&&merged[0][0]===0&&merged[0][1]===current.total_chars;
    }
    target.unit_count ??= prior.unit_count;
    target.output_references=[...new Set([...(target.output_references||[]),...(prior.output_references||[])])];
    if(prior.source_summary && prior.source_summary!==target.source_summary)
      target.migrated_summaries=[...new Set([...(target.migrated_summaries||[]),prior.source_summary])];
    target.complete=Number.isInteger(target.unit_count)&&Object.values(target.delivered_units).filter(unit=>unit.delivered).length===target.unit_count;
    if(Number.isInteger(target.unit_count))target.pending_units=Array.from({length:target.unit_count},(_,i)=>i+1).filter(i=>!target.delivered_units[i]?.delivered);
  }
  async function sourceKey(id, ledger, path, result) {
    const binding=await options.resolveSource?.(id,path,result);
    if(!binding)return normalized(path);
    if(!binding.owner||!binding.scope||!binding.source_id||!Array.isArray(binding.aliases))throw new Error('source_identity_invalid');
    ledger.aliases ??= {};
    const scope=JSON.stringify([binding.owner,binding.scope]), aliases=[...new Set([path,...binding.aliases].map(normalized))];
    const priorKeys=[...new Set([...aliases,...aliases.map(alias=>ledger.aliases[scope+':'+alias]).filter(Boolean)])];
    // A raw file read has no extraction revision. It may use the latest exact,
    // broker-registered alias, but cannot transfer evidence across revisions.
    const existing=aliases.map(alias=>ledger.sources[ledger.aliases[scope+':'+alias]]).find(source=>source && !source.archived
      && source.source_identity?.owner===binding.owner && source.source_identity?.scope===binding.scope
      && (!binding.sha256 || source.sha256===binding.sha256));
    if (binding.version == null && existing) return existing.path;
    const sourceIdentity={owner:binding.owner,scope:binding.scope,source_id:normalized(binding.source_id),
      version:binding.version ?? null,sha256:binding.sha256 ?? null};
    const serialized=JSON.stringify(sourceIdentity);
    const key='source:'+createHash('sha256').update(serialized).digest('hex');
    ledger.sources[key] ??= {path:key,units:[],complete:false,status:'pending',source_identity:sourceIdentity,sha256:binding.sha256 ?? null};
    for(const alias of aliases)ledger.aliases[scope+':'+alias]=key;
    ledger.version_aliases ??= {};
    for(const alias of aliases)ledger.version_aliases[serialized+':'+alias]=key;
    for(const priorKey of priorKeys)if(priorKey!==key&&ledger.sources[priorKey]) {
      const prior=ledger.sources[priorKey];
      // Old unversioned evidence remains available by its saved key. Unknown
      // provenance never becomes proof for a newly extracted source version.
      if(JSON.stringify(prior.source_identity)===serialized)mergeEvidence(ledger.sources[key],prior);
      if(!prior.source_identity || prior.source_identity.owner===binding.owner && prior.source_identity.scope===binding.scope) {
        prior.archived=true;prior.superseded_by=key;
      }
    }
    return key;
  }
  function summary(ledger, offset = 0, limit = 30) {
    const sources = Object.values(ledger.sources).filter(source=>!source.archived);
    const completed = sources.filter(source => source.complete).length;
    const unsupported = sources.filter(source => source.supported === false).length;
    const rows = sources.slice(offset, offset + limit).map(({ delivered_units, units, pending_units, source_summary, output_references, ...source }) => ({
      ...source, delivered_unit_count: Object.values(delivered_units ?? {}).filter(unit => unit.delivered).length,
      pending_unit_count: pending_units?.length ?? null, pending_units_preview: pending_units?.slice(0, 10) ?? [],
      has_saved_summary: Boolean(source_summary), output_reference_count: output_references?.length ?? 0,
      detail_tool: 'read_task_progress(source_path=path)' }));
    return { summary: ledger.summary, next_steps: ledger.next_steps, manifest_complete: ledger.manifest_complete,
      archived_source_paths:Object.values(ledger.sources).filter(source=>source.archived).map(source=>source.path),
      coverage: { source_count: sources.length, complete_count: completed, unsupported_count: unsupported,
        scope: 'tool_result_delivery', semantic_completeness: 'not_guaranteed',
        pending_count: sources.length - completed - unsupported,
        excluded_entries: ledger.excluded_entries ?? 0, unavailable_entries: ledger.unavailable_entries ?? 0,
        skipped_entries: ledger.skipped_entries ?? 0,
        reading_complete: ledger.manifest_complete && sources.length === completed && !(ledger.unavailable_entries > 0) },
      sources: rows, offset, next_offset: offset + rows.length < sources.length ? offset + rows.length : null };
  }
  const api = {
    async recordTeaching(id, references) {
      const ledger = await load(id), keys = new Set();
      for(const ref of references || []) {
        if(ref.type !== 'reading' || typeof ref.material_id !== 'string' || !Number.isInteger(ref.material_revision) || !Number.isInteger(ref.page))continue;
        const key=await sourceKey(id,ledger,`reading:${ref.material_id}@${ref.material_revision}`,ref);keys.add(key);
        const digest=ref._source_binding?.sha256;
        const previous=ledger.sources[key];
        const source=previous && (!digest||!previous.sha256||previous.sha256===digest) ? previous : {path:key,title:ref.title,units:[],complete:false,status:'partially_delivered',semantic_completeness:'not_guaranteed'};
        source.sha256=digest || source.sha256;
        source.units=[...new Map([...source.units,{page:ref.page}].map(unit=>[unit.page,unit])).values()];
        // Native references prove these locators were returned. They don't
        // include character spans or total scope, so never assert completion.
        source.native_delivered_locators=source.units.map(unit=>unit.page).sort((a,b)=>a-b);
        source.coverage_source='native_reading_tool_references';ledger.sources[key]=source;
      }
      if(keys.size)await save(id,ledger);
      return [...keys];
    },
    async recordDocument(id, requestedPath, result) {
      if (!result?.ok) return;
      const ledger = await load(id);
      const key = await sourceKey(id,ledger,requestedPath,result);
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
        const key = await sourceKey(id,ledger,entry.path,entry);
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
      if(input.source_path && !ledger.sources[input.source_path]) input={...input,source_path:await sourceKey(id,ledger,input.source_path,{})};
      const invalid = () => Object.assign(new Error('Progress is too large or malformed. Save per-source notes with source_path/source_summary and store full outputs in task files; no existing progress was changed.'), { code: 'task_progress_size_limit' });
      if (input.summary !== undefined && (typeof input.summary !== 'string' || input.summary.length > 12000)) throw invalid();
      if (input.next_steps !== undefined && (!Array.isArray(input.next_steps) || input.next_steps.length > 100
        || input.next_steps.some(value => typeof value !== 'string' || value.length > 1000))) throw invalid();
      if (input.source_path !== undefined && (typeof input.source_path !== 'string' || !ledger.sources[input.source_path]))
        throw Object.assign(new Error('Unknown source_path. Use read_task_progress to get its recorded path. Known paths: '+Object.keys(ledger.sources).slice(0,12).join(', ')),{code:'task_progress_source_unknown'});
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
      const ledger = await load(id);
      const source = ledger.sources[path] ?? ledger.sources[await sourceKey(id,ledger,path,{})];
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
  // Serialize the entire read/modify/write operation, including asynchronous
  // broker resolution, not only the final write of a stale JSON snapshot.
  return Object.fromEntries(Object.entries(api).map(([name, operation]) => [name, (id, ...args) => {
    const job=(operations.get(id) ?? Promise.resolve()).then(()=>operation(id,...args));
    const settled=job.catch(()=>{});operations.set(id,settled);
    settled.then(()=>{if(operations.get(id)===settled)operations.delete(id);});
    return job;
  }]));
}
