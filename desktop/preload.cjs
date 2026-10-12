'use strict';
const { contextBridge, ipcRenderer } = require('electron');

// Only the packaged startup document receives these display-only stages.
let startupStage = 'starting';
let startupTipsReady = false;
let startupTipTimer = null;
let startupTipIndex = 0;
let startupMotionQuery = null;
const startupTips = Object.freeze([
  'Start with one document and connect reading, questions, and understanding.',
  'Keep every practice attempt and continue where you left off.',
  'Adjust model and API settings in the app whenever needed.',
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
    starting: 'Preparing learning services...',
    opening: 'Learning services are ready. Opening your learning space...',
    'error-services': 'Local learning services could not finish starting.',
    'error-page': 'Local services are ready, but the learning page could not open.',
    'error-cleanup': 'Cleanup from the previous startup is unfinished. Try again.',
  };
  const message = messages[startupStage];
  document.documentElement.dataset.startupStage = startupStage;
  status.textContent = message;
  progress.hidden = failed;
  progress.setAttribute('aria-valuetext', message);
  content.setAttribute('aria-busy', String(!failed));
  note.textContent = failed ? 'Existing learning records and model settings were preserved. Retry or view the startup logs.' : 'The app will open when ready. Your workspaces, courses, and learning records are preserved.';
  const phase = document.getElementById('startup-phase-label');
  if (phase) phase.textContent = failed ? 'Retry needed' : startupStage === 'opening' ? 'Opening shortly' : 'Preparing';
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
}
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
      if (!(await ipcRenderer.invoke('deepsteam:open-startup-logs'))) document.getElementById('startup-note').textContent = 'Could not open the log folder. Check File Explorer or reopen the app and try again.';
    } catch { document.getElementById('startup-note').textContent = 'Could not open the log folder. Reopen the app and try again.'; }
    finally { logs.disabled = false; }
  });
}, { once: true });
contextBridge.exposeInMainWorld('deepsteamDesktop', Object.freeze({
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
