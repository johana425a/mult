/** Compose official Cordis, account PKCE, LLM adapters, tools, agent loop and durable sessions. */
import { Context } from '@deepseek-ai/cordis';
import LlmRuntime from '@deepseek-ai/dsh-llm';
import * as PiAi from '@deepseek-ai/dsh-llm-pi-ai';
import AccountPlatform from '@deepseek-ai/dsh-deepseek-account-platform';
import * as AccountLlm from '@deepseek-ai/dsh-llm-deepseek-account';
import * as ApiKeyLlm from '@deepseek-ai/dsh-llm-deepseek-api-key';
import WebServer from '@deepseek-ai/dsh-host-webserver';
import Authorization from '@deepseek-ai/dsh-authorization';
import AttachmentLocal from '@deepseek-ai/dsh-attachment-local';
import AgentRegistry from '@deepseek-ai/dsh-agent';
import AgentLoop from '@deepseek-ai/dsh-agent-loop';
import SessionStore from '@deepseek-ai/dsh-session';
import SessionProjection from '@deepseek-ai/dsh-session-projection';
import SessionJsonl from '@deepseek-ai/dsh-session-persistence-jsonl';
import SystemPrompt from '@deepseek-ai/dsh-system-prompt';
import Tools from '@deepseek-ai/dsh-tools';
import { join } from 'node:path';
import { DeepSteamCredentials } from './credentials.mjs';
import { createWorkspaceAdapter } from './workspaces.mjs';
import { createExecutionTasks } from './execution_tasks.mjs';
import { createInteractionSurfaces } from './interaction_surfaces.mjs';

export const COMMIT = 'd743267388641bc76f17c45ce8b4c231aed1d32c';
export const TOOL_DESCRIPTIONS = Object.freeze({});
const PERSONA = 'You are DeepSteam. Complete tasks using the user\'s selected model and tools.';

/** Create only this application profile. No global .dsh state or ambient cloud keys are read. */
export async function createHost(options) {
  const ctx = new Context();
  await ctx.plugin(DeepSteamCredentials, { python: options.python, helper: options.credentialHelper, path: join(options.profile, 'credentials.dpapi') });
  await ctx.plugin(Authorization);
  await ctx.plugin(LlmRuntime);
  await ctx.plugin(AttachmentLocal, { dshHome: options.profile });
  await ctx.plugin(WebServer, { host: '127.0.0.1', port: options.port, compression: 'none' });
  await ctx.plugin(AccountPlatform, { desktopPlatform: 'win32', requestTimeoutMs: 30000, balanceTimeoutMs: 10000 });
  await ctx.plugin(AccountLlm, { reasoningEffort: 'high', retryPolicy: { mode: 'normal', maxRetries: 0 } });
  await ctx.plugin(ApiKeyLlm, { apiKeyEnv: 'DEEPSTEAM_REQUEST_KEY', reasoningEffort: 'high', retryPolicy: { mode: 'normal', maxRetries: 0 } });
  let piProviders = PiAi.Config({ providers: {} }).providers.get();
  // A single official pi-ai plugin owns its catalog; route additions use its
  // supported volatile-update path instead of mounting duplicate catalogs.
  const dynamicPiAi = child => PiAi.apply(child, { providers: { get: () => piProviders } });
  dynamicPiAi.inject = PiAi.inject;
  await ctx.plugin(dynamicPiAi);
  const configureWorkspaceProvider = (provider, profile) => {
    const next = PiAi.Config({ providers: { ...piProviders, [provider]: profile } }).providers.get();
    piProviders = next; ctx.emit('loader/volatile-update');
  };
  await ctx.plugin(SessionStore);
  await ctx.plugin(SessionProjection);
  await ctx.plugin(SessionJsonl, { root: options.sessions, compression: 'none' });
  await ctx.plugin(SystemPrompt, { personaPrefix: PERSONA });
  await ctx.plugin(Tools, { mode: 'native' });
  await ctx.plugin(AgentRegistry);
  await ctx.plugin(AgentLoop, { agents: [] });
  const workspaces = await createWorkspaceAdapter(ctx, { ...options, configureWorkspaceProvider });
  const interactions = await createInteractionSurfaces(ctx, { ...options, workspaces });
  const tasks = await createExecutionTasks({ profile: options.profile, workspaces, interactions });
  ctx.effect(() => () => tasks.close());
  return { ctx, workspaces, tasks, interactions };
}
