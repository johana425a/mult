'use strict';
const { contextBridge, ipcRenderer } = require('electron');

// Only the packaged startup document receives these display-only stages.
let startupStage = 'starting';
let startupTipsReady = false;
let startupTipTimer = null;
let startupTipIndex = 0;
let startupMotionQuery = null;
const startupTips = Object.freeze([
  '从一份资料开始，连起阅读、提问与理解。',
  '保留每一次练习，下一次从上次的地方继续。',
  '模型与接口设置，仍可在应用内自由调整。',
]);
function isStartupDocument() {
  return window.location.protocol === 'file:' && document.documentElement.dataset.deepsteamStartup === 'true';
}
function stopStartupTips() {
  if (startupTipTimer !== null) window.clearInterval(startupTipTimer);
  startupTipTimer = null;
}
function updateStartupTips() {
  if (!startupTipsReady || !isStartupDocument()) return;
  const paused = document.hidden || startupStage.startsWith('error-');
  document.documentElement.dataset.startupPaused = String(paused);
  // Tips describe existing capabilities, never invented startup operations. They
  // rotate independently of service readiness and cannot delay navigation.
  if (paused || startupMotionQuery?.matches) { stopStartupTips(); return; }
  if (startupTipTimer !== null) return;
  startupTipTimer = window.setInterval(() => {
    const tip = document.getElementById('startup-tip');
    if (!tip) { stopStartupTips(); return; }
    startupTipIndex = (startupTipIndex + 1) % startupTips.length;
    tip.textContent = startupTips[startupTipIndex];
    tip.dataset.tipVariant = tip.dataset.tipVariant === '0' ? '1' : '0';
  }, 4200);
}
function renderStartupStage() {
  if (!isStartupDocument()) return;
  const content = document.getElementById('startup-content');
  const status = document.getElementById('startup-status');
  const progress = document.getElementById('startup-progress');
  const note = document.getElementById('startup-note');
  const actions = document.getElementById('startup-actions');
  const retry = document.getElementById('startup-retry');
  if (!content || !status || !progress || !note) return;
  const failed = startupStage.startsWith('error-');
  const messages = {
    starting: '正在准备学习服务……',
    opening: '学习服务已就绪，正在打开学习界面……',
    'error-services': '本机学习服务未能完成启动。',
    'error-page': '本机服务已启动，学习页面未能打开。',
    'error-cleanup': '上次启动尚未完成清理，请重试。',
  };
  const message = messages[startupStage];
  document.documentElement.dataset.startupStage = startupStage;
  status.textContent = message;
  progress.hidden = failed;
  progress.setAttribute('aria-valuetext', message);
  content.setAttribute('aria-busy', String(!failed));
  note.textContent = failed ? '已有学习记录和模型设置已保留。可以重试，或查看启动日志。' : '准备完成后会自动进入。你的工作区、课程与学习记录会保留。';
  const phase = document.getElementById('startup-phase-label');
  if (phase) phase.textContent = failed ? '需要重试' : startupStage === 'opening' ? '即将进入' : '准备中';
  const servicesReady = startupStage === 'opening' || startupStage === 'error-page';
  const serviceStep = document.getElementById('startup-step-services');
  const pageStep = document.getElementById('startup-step-page');
  if (serviceStep) {
    serviceStep.dataset.state = servicesReady ? 'complete' : 'active';
    if (servicesReady) serviceStep.removeAttribute('aria-current');
    else serviceStep.setAttribute('aria-current', 'step');
  }
  if (pageStep) {
    pageStep.dataset.state = servicesReady ? 'active' : 'pending';
    if (servicesReady) pageStep.setAttribute('aria-current', 'step');
    else pageStep.removeAttribute('aria-current');
  }
  if (actions) actions.hidden = !failed;
  if (retry) retry.disabled = !failed;
  updateStartupTips();
  renderStartupServices();
}
// deepsteam:startup-services: tick each part as its local service answers.
const startupServiceDetails = Object.freeze({
  engine: ['恢复对话与学习记录', '检查知识库与精通路径', '载入模型与工具设置'],
  harness: ['载入工作区与本地工具', '核对文件访问范围'],
  classroom: ['准备课堂场景与讲稿生成'],
  renderer: ['准备 PDF、幻灯片与公式渲染'],
  interface: ['启动学习界面'],
  portal: ['连通各项服务'],
});
let startupServices = {};
let startupDetailTick = 0;
let startupDetailTimer = null;
function renderStartupServices() {
  if (!isStartupDocument()) return;
  const names = Object.keys(startupServiceDetails);
  const servicesDone = startupStage === 'opening' || startupStage === 'error-page';
  const failed = startupStage.startsWith('error-');
  let ready = 0;
  for (const name of names) {
    const row = document.getElementById(`startup-svc-${name}`);
    if (!row) continue;
    const up = servicesDone || startupServices[name] === true;
    if (up) ready += 1;
    row.dataset.state = up ? 'complete' : failed ? 'pending' : 'active';
    const detail = row.querySelector('.svc-detail');
    const lines = startupServiceDetails[name];
    if (detail) detail.textContent = up ? '已就绪' : lines[startupDetailTick % lines.length];
  }
  const phase = document.getElementById('startup-phase-label');
  if (phase && startupStage === 'starting') phase.textContent = `准备中 · ${ready}/${names.length}`;
  if (startupDetailTimer === null && !failed && !servicesDone && !startupMotionQuery?.matches) {
    startupDetailTimer = window.setInterval(() => { startupDetailTick += 1; renderStartupServices(); }, 2600);
  }
  if (startupDetailTimer !== null && (failed || servicesDone)) { window.clearInterval(startupDetailTimer); startupDetailTimer = null; }
}
ipcRenderer.on('deepsteam:startup-services', (_event, states) => {
  if (!states || typeof states !== 'object') return;
  startupServices = Object.fromEntries(Object.keys(startupServiceDetails).map(name => [name, states[name] === true]));
  renderStartupServices();
});
// DeepSteam 2026-10-16 transition
ipcRenderer.on('deepsteam:startup-exit', () => {
  if (isStartupDocument()) document.documentElement.classList.add('ds-exit');
});
ipcRenderer.on('deepsteam:startup-status', (_event, stage) => {
  if (!['starting', 'opening', 'error-services', 'error-page', 'error-cleanup'].includes(stage)) return;
  startupStage = stage;
  renderStartupStage();
});
window.addEventListener('DOMContentLoaded', () => {
  renderStartupStage();
  if (!isStartupDocument()) return;
  startupTipsReady = true;
  startupMotionQuery = window.matchMedia?.('(prefers-reduced-motion: reduce)') || null;
  startupMotionQuery?.addEventListener('change', updateStartupTips);
  document.addEventListener('visibilitychange', updateStartupTips);
  window.addEventListener('pagehide', stopStartupTips, { once: true });
  updateStartupTips();
  const retry = document.getElementById('startup-retry');
  const logs = document.getElementById('startup-logs');
  retry?.addEventListener('click', async () => {
    retry.disabled = true;
    try { if (!(await ipcRenderer.invoke('deepsteam:retry-startup'))) renderStartupStage(); }
    catch { renderStartupStage(); }
  });
  logs?.addEventListener('click', async () => {
    logs.disabled = true;
    try {
      if (!(await ipcRenderer.invoke('deepsteam:open-startup-logs'))) document.getElementById('startup-note').textContent = '未能打开日志文件夹。请检查文件管理器，或重新打开应用后再试。';
    } catch { document.getElementById('startup-note').textContent = '未能打开日志文件夹。请重新打开应用后再试。'; }
    finally { logs.disabled = false; }
  });
}, { once: true });
contextBridge.exposeInMainWorld('deepsteamDesktop', Object.freeze({
  domesticVideo: (options) => ipcRenderer.invoke('deepsteam:domestic-video', options),
  bilibiliPlayback: (options) => ipcRenderer.invoke('deepsteam:bilibili-playback', options),
  bilibiliSessionStatus: () => ipcRenderer.invoke('deepsteam:bilibili-status'),
  onBilibiliSessionChanged: (callback) => {
    if (typeof callback !== 'function') return () => {};
    const listener = () => callback();
    ipcRenderer.on('deepsteam:bilibili-session-changed', listener);
    return () => ipcRenderer.removeListener('deepsteam:bilibili-session-changed', listener);
  },
  openBilibiliLogin: () => ipcRenderer.invoke('deepsteam:bilibili-login'),
  signOutBilibili: () => ipcRenderer.invoke('deepsteam:bilibili-signout'),
  importBilibiliSubtitles: (options) => ipcRenderer.invoke('deepsteam:bilibili-subtitles', options),
  openOfficial: (url) => ipcRenderer.invoke('deepsteam:open-official', String(url)),
  pickWorkspaceDirectory: () => ipcRenderer.invoke('deepsteam:pick-workspace-directory'),
  openWorkspaceDirectory: (directory) => ipcRenderer.invoke('deepsteam:open-workspace-directory', String(directory)),
  openRegisteredWorkspaceDirectory: (workspaceId) => ipcRenderer.invoke('deepsteam:open-registered-workspace-directory', String(workspaceId)),
  // No renderer-supplied flags: native confirmation owns all uninstall choices.
  openUninstaller: () => ipcRenderer.invoke('deepsteam:open-uninstaller'),
  // Internal transport capability only. Callers must never present this URL as
  // user configuration or navigation; authority is checked again by main.
  webSocketUrl: (requestPath) => typeof requestPath === 'string' ? ipcRenderer.sendSync('deepsteam:websocket-url', requestPath) : null,
  version: '1.1.0',
}));
