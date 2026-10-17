/** Public diagnostics retain actionable detail, never credentials or raw headers. */
import { randomUUID } from 'node:crypto';

export function safeMessage(value) {
  return String(value ?? 'Execution did not complete.')
    .replace(/Bearer\s+[^\s"']+/gi, 'Bearer [redacted]')
    .replace(/((?:api[_-]?key|authorization|password|secret|token)\s*[:=]\s*)[^\s,;}]+/gi, '$1[redacted]')
    .replace(/\b(?:sk-|dsexec_)[A-Za-z0-9_-]{12,}\b/g, '[credential-reference]')
    .slice(0, 2400);
}

export function executionError(cause, phase = 'execution', traceId = randomUUID()) {
  const inner = cause?.failure ?? cause?.error ?? cause ?? {};
  const code = /^[A-Za-z0-9_.:-]{1,100}$/.test(inner.code ?? '') ? inner.code : 'EXECUTION_FAILED';
  return { code, phase, message: safeMessage(inner.message ?? String(cause)), trace_id: traceId,
    retryable: ['ECONNRESET', 'ETIMEDOUT', 'MODEL_OVERLOADED'].includes(code)
      || code === 'SERVER' && /HTTP (429|502|503|504)\b/.test(inner.message || ''),
    ...(Number.isInteger(inner.exit_code) ? { exit_code: inner.exit_code } : {}) };
}

export function reasoningDeclaration(route) {
  // The loopback execution adapter already freezes the exact provider settings.
  // Advertise that exact effort to Harness; opaque dsexec model ids have no
  // upstream catalog entry from which pi-ai could infer reasoning support.
  const effort = route?.resolved_model?.reasoning_effort;
  const normalized = ({ none: 'off', minimal: 'minimal', low: 'low', medium: 'medium', high: 'high',
    xhigh: 'xhigh', max: 'xhigh' })[effort] ?? effort;
  const levels = new Set(['off', 'minimal', 'low', 'medium', 'high', 'xhigh']);
  if (!effort || normalized === 'off') return { reasoningEfforts: false };
  if (!levels.has(normalized)) throw Object.assign(new Error(`Unsupported reasoning effort: ${effort}`), { code: 'UNSUPPORTED_REASONING_EFFORT' });
  // Only advertise the selected level. A null mapping passes pi-ai's own
  // loose config path but fails Harness profile validation on the next load.
  return { reasoningEfforts: { [normalized]: effort } };
}

export function harnessReasoning(route) {
  const value = route?.resolved_model?.reasoning_effort;
  return value === 'none' ? 'off' : value === 'max' ? 'xhigh' : value;
}
