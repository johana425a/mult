/**
 * Course model configuration station-to-runtime-stage contract.
 *
 * One station control may cover several runtime stages: classroom interaction includes multi-agent
 * chat (chat-adapter), quiz grading (quiz-grade), and the PBL runtime (pbl-v2-runtime),
 * whose :instructor/:open-task/:evaluate/:simulator subkeys inherit
 * through getUserStageRoute parent fallback. Write overrides for the whole key group
 * and clear them together when restoring inheritance; partial writes otherwise let stages fall back
 * to the main model, as seen in PR #1644 when quiz-grade and
 * pbl-v2-runtime:instructor failed to inherit interaction overrides.
 *
 * tests/config/station-stage-keys.test.ts validates keys against LLM_STAGES
 * to prevent client/server drift.
 */
export const STATION_STAGE_KEYS: Record<string, readonly string[]> = {
  'web-research': ['web-search-query-rewrite'],
  outline: ['scene-outlines-stream'],
  agents: ['agent-profiles'],
  'scene-content': ['scene-content'],
  'scene-actions': ['scene-actions'],
  interaction: ['chat-adapter', 'quiz-grade', 'pbl-chat', 'pbl-v2-runtime'],
};
