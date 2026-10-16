/** Lazy model-facing surfaces over official, pinned Harness plugins. */
import SessionQuery from '@deepseek-ai/dsh-session-query';
import Subagents from '@deepseek-ai/dsh-subagent';
import * as Spawn from '@deepseek-ai/dsh-subagent-spawn-in-process';
import * as SubagentTools from '@deepseek-ai/dsh-tool-subagent';
import * as SubagentControl from '@deepseek-ai/dsh-tool-subagent-control';
import Skills from '@deepseek-ai/dsh-skill';
import * as FileSkills from '@deepseek-ai/dsh-skill-filesystem';
import * as SkillTools from '@deepseek-ai/dsh-tool-skill';
import Goals from '@deepseek-ai/dsh-goal';
import * as GoalDriver from '@deepseek-ai/dsh-goal-round-driver';
import * as GoalTools from '@deepseek-ai/dsh-tool-goal';
import Schedule from '@deepseek-ai/dsh-schedule';
import * as ScheduleTools from '@deepseek-ai/dsh-tool-schedule';
import BrowserUse from '@deepseek-ai/dsh-browser-use';
import ComputerUse from '@deepseek-ai/dsh-computer-use';
import { readFile, stat } from 'node:fs/promises';
import { join } from 'node:path';

export const CAPABILITY_GROUPS = ['subagents', 'skills', 'goals', 'schedule', 'browser', 'computer', 'mcp'];

export async function createCapabilities(ctx, options) {
  await ctx.plugin(SessionQuery);
  await ctx.plugin(Subagents);
  await ctx.plugin(Spawn, { providerName: 'spawn' });
  await ctx.plugin(Skills);
  // Default project roots remain available, but user roots belong to DeepSteam.
  await ctx.plugin(FileSkills, { dshHome: options.profile, agentsHome: join(options.profile, 'agents'), watch: false });
  await ctx.plugin(Goals);
  await ctx.plugin(GoalDriver);
  await ctx.plugin(Schedule);
  await ctx.plugin(BrowserUse);
  await ctx.plugin(ComputerUse);
  const groups = new WeakMap();
  const live = new Map();
  let browserRuntime, computerRuntime;
  let desktopQueue = Promise.resolve();
  ctx.on('tools/execute', async (execution, next) => {
    if (!execution.name.startsWith('cua_driver_native__')) return next();
    const previous = desktopQueue;
    let release; desktopQueue = new Promise(resolve => { release = resolve; });
    try { await previous; execution.signal.throwIfAborted(); return await next(); }
    finally { release(); }
  });
  async function enable(agent, group) {
    if (!CAPABILITY_GROUPS.includes(group)) throw new Error('capability_unknown');
    let loaded = groups.get(agent);
    if (!loaded) { loaded = new Map(); groups.set(agent, loaded); }
    if (loaded.has(group)) return loaded.get(group);
    const job = (async () => {
      const scope = agent.ctx;
      if (group === 'subagents') {
        await scope.plugin(SubagentTools, { provider: 'spawn' });
        await scope.plugin(SubagentControl);
      } else if (group === 'skills') await scope.plugin(SkillTools);
      else if (group === 'goals') await scope.plugin(GoalTools);
      else if (group === 'schedule') await scope.plugin(ScheduleTools);
      else if (group === 'browser') {
        const executablePath = options.chromium;
        if (!executablePath || !(await stat(executablePath).catch(() => null))?.isFile()) {
          throw Object.assign(new Error('browser_runtime_missing'), { code: 'browser_runtime_missing' });
        }
        const provider = await import('@deepseek-ai/dsh-experimental-browser-use-playwright-mcp');
        // The official browser provider initializes on agent/created. A lazy
        // load happens after that event, so activate its own handler once for
        // this Agent without re-emitting creation to unrelated host services.
        browserRuntime ??= (async () => {
          const activations = [];
          await ctx.plugin({ name: 'deepsteam-session-browser', inject: provider.inject,
          async apply(inner) {
            const adapter = new Proxy(inner, { get(target, name) {
              if (name === 'on') return (event, callback, ...rest) => {
                if (event === 'agent/created') { activations.push(callback); return () => {}; }
                return target.on(event, callback, ...rest);
              };
              return Reflect.get(target, name);
            } });
            await provider.apply(adapter, provider.Config({ mode: 'launch', executablePath, headless: false, toolCallTimeoutMs: 60000 }));
          } });
          return activations;
        })().catch(cause => { browserRuntime = undefined; throw cause; });
        for (const activate of await browserRuntime) await activate({ agent, source: 'resume', signal: new AbortController().signal });
      } else if (group === 'computer') {
        if (process.platform !== 'win32') throw Object.assign(new Error('computer_platform_unsupported'), { code: 'computer_platform_unsupported' });
        const provider = await import('@deepseek-ai/dsh-experimental-computer-use-cua-driver-native');
        // This provider owns one Host-wide desktop. Official computerUse enforces
        // exclusivity; tools are scoped to the requesting live Agent.
        computerRuntime ??= ctx.plugin(provider).then(() => true).catch(cause => { computerRuntime = undefined; throw cause; });
        await computerRuntime;
      } else if (group === 'mcp') {
        let servers = [];
        try { servers = JSON.parse(await readFile(join(options.profile, 'mcp-servers.json'), 'utf8')).servers ?? []; }
        catch (cause) { if (cause.code !== 'ENOENT') throw cause; }
        if (!servers.length) return { capability: group, status: 'configuration_required', tools: [] };
        const mcp = await import('@deepseek-ai/dsh-mcp-client');
        for (const server of servers) await scope.plugin(mcp, { ...server, failOnStartupError: true });
      }
      const result = { capability: group, status: 'ready', tools: scope.tools.schemas(agent).map(tool => tool.name) };
      live.set(`${agent.id}:${group}`, result);
      return result;
    })();
    loaded.set(group, job);
    try { return await job; } catch (cause) { loaded.delete(group); throw cause; }
  }
  return { enable, status: () => ({ available: CAPABILITY_GROUPS, loaded: [...live.values()], mcp_default_servers: 0,
    browser: { provider: 'playwright-mcp', version: '0.0.80', isolated_profile: true },
    computer: { provider: 'cua-driver-native', version: '0.28.0', platform: process.platform, on_demand: true } }) };
}
