'use strict';

// DeepSteam-owned session bridge. Only caption text crosses into the reading
// store; account cookies never enter the renderer, Python, a model or a log.
const MAX_BYTES = 4 * 1024 * 1024;
function allowedUrl(value, suffix) {
  try {
    const url = new URL(value);
    const host = url.hostname.toLowerCase();
    return url.protocol === 'https:' && !url.username && !url.password && (!url.port || url.port === '443')
      && (host === suffix || host.endsWith('.' + suffix));
  } catch { return false; }
}
async function boundedJson(response) {
  if (!response.ok) throw new Error('CAPTION_REQUEST_FAILED');
  if (Number(response.headers.get('content-length') || 0) > MAX_BYTES) throw new Error('CAPTION_TOO_LARGE');
  const reader = response.body.getReader();
  const chunks = [];
  let size = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > MAX_BYTES) { await reader.cancel(); throw new Error('CAPTION_TOO_LARGE'); }
      chunks.push(Buffer.from(value));
    }
  } finally { reader.releaseLock(); }
  return JSON.parse(Buffer.concat(chunks).toString('utf8'));
}
function pickSubtitle(player) {
  const rows = player?.subtitle?.subtitles;
  if (!Array.isArray(rows)) return null;
  const candidates = rows.filter(row => row && typeof row.subtitle_url === 'string');
  return candidates.find(row => /^((ai-)?zh)(-|$)/i.test(row.lan || '')) || candidates[0] || null;
}
function createBilibiliBridge({ BrowserWindow, getWindow, getSession, authorize, serviceRequest, diagnostic = () => {} }) {
  let loginWindow = null;
  let importing = false;
  let statusRequest = null;
  function observeSessionChanges(callback) {
    const cookies = getSession().cookies;
    let pending = null;
    const changed = (_event, cookie) => {
      const domain = String(cookie?.domain || '').replace(/^\./, '').toLowerCase();
      if (domain !== 'bilibili.com' && !domain.endsWith('.bilibili.com')) return;
      if (!['SESSDATA', 'DedeUserID', 'bili_jct'].includes(cookie?.name)) return;
      clearTimeout(pending);
      pending = setTimeout(() => callback(), 300);
    };
    cookies.on('changed', changed);
    return () => { clearTimeout(pending); cookies.removeListener('changed', changed); };
  }
  // Electron's Chromium network service rejects a manually supplied Referer
  // header here (ERR_BLOCKED_BY_CLIENT). Keep cookies in the owned session and
  // use the API without that forbidden header; do not weaken browser security.
  const apiHeaders = { Accept: 'application/json', 'User-Agent': 'DeepSteam/ImmersiveReading' };
  async function sessionStatus(event) {
    if (!authorize(event)) return { status: 'denied' };
    if (!statusRequest) {
      statusRequest = (async () => {
        try {
          const response = await getSession().fetch('https://api.bilibili.com/x/web-interface/nav', {
            credentials: 'include', headers: apiHeaders, cache: 'no-store', redirect: 'error',
            signal: AbortSignal.timeout(15000) });
          const body = await boundedJson(response);
          if (body.code === 0 && body.data?.isLogin === true) return { status: 'signed_in' };
          if (body.code === -101 || body.data?.isLogin === false) return { status: 'signed_out' };
          return { status: 'request_failed' };
        } catch { return { status: 'request_failed' }; }
        finally { statusRequest = null; }
      })();
    }
    const result = await statusRequest;
    return authorize(event) ? result : { status: 'denied' };
  }
  async function openLogin(event) {
    if (!authorize(event)) return { status: 'denied' };
    if (loginWindow && !loginWindow.isDestroyed()) { loginWindow.show(); loginWindow.focus(); return { status: 'opened' }; }
    loginWindow = new BrowserWindow({ width: 1040, height: 760, title: 'Bilibili sign-in - DeepSteam',
      parent: getWindow(), show: true, autoHideMenuBar: true,
      webPreferences: { session: getSession(), sandbox: true, contextIsolation: true,
        nodeIntegration: false, webSecurity: true, allowRunningInsecureContent: false } });
    loginWindow.webContents.setWindowOpenHandler(({ url }) => {
      if (allowedUrl(url, 'bilibili.com')) void loginWindow.loadURL(url);
      return { action: 'deny' };
    });
    loginWindow.webContents.on('will-navigate', (navigation, url) => {
      if (!allowedUrl(url, 'bilibili.com')) navigation.preventDefault();
    });
    loginWindow.on('closed', () => { loginWindow = null; });
    await loginWindow.loadURL('https://passport.bilibili.com/login');
    return { status: 'opened' };
  }
  async function importSubtitles(event, options) {
    if (!authorize(event) || !options || !/^[0-9a-f]{16}$/.test(options.materialId || '')
        || !/^(?:ws_[0-9a-f]{32})?$/.test(options.workspaceId || '')) return { status: 'denied' };
    if (importing) return { status: 'busy' };
    importing = true;
    let step = 'source';
    try {
      const query = new URLSearchParams({ dt_workspace: options.workspaceId || '' });
      const source = await serviceRequest(`/api/contest/internal/bilibili-source/${options.materialId}?${query}`);
      diagnostic('source_ready');
      if (!authorize(event)) return { status: 'denied' };
      const params = new URLSearchParams({ bvid: source.bvid, cid: String(source.cid) });
      const ownedSession = getSession();
      const headers = apiHeaders;
      step = 'player';
      const response = await ownedSession.fetch(`https://api.bilibili.com/x/player/wbi/v2?${params}`,
        { credentials: 'include', headers, cache: 'no-store', redirect: 'error', signal: AbortSignal.timeout(15000) });
      diagnostic('player_response', { http_status: response.status });
      const payload = await boundedJson(response);
      diagnostic('player_data', { api_code: Number.isFinite(payload.code) ? payload.code : null,
        login_required: payload.data?.need_login_subtitle === true,
        track_count: Array.isArray(payload.data?.subtitle?.subtitles) ? payload.data.subtitle.subtitles.length : 0 });
      if (payload.code !== 0 || !payload.data) return { status: 'request_failed' };
      const track = pickSubtitle(payload.data);
      if (!track && payload.data.need_login_subtitle) {
        const account = await sessionStatus(event);
        // A failed API call or a player/account mismatch is not proof of logout.
        if (account.status === 'signed_out') return { status: 'login_required' };
        return { status: account.status === 'signed_in' ? 'session_mismatch' : account.status };
      }
      if (!track) return { status: 'no_track' };
      const subtitleUrl = track.subtitle_url.startsWith('//') ? 'https:' + track.subtitle_url : track.subtitle_url;
      if (!allowedUrl(subtitleUrl, 'hdslb.com')) return { status: 'request_failed' };
      step = 'captions';
      const captions = await boundedJson(await ownedSession.fetch(subtitleUrl, {
        credentials: 'omit', redirect: 'error', cache: 'no-store', headers: { Accept: 'application/json' },
        signal: AbortSignal.timeout(15000) }));
      if (!Array.isArray(captions.body) || !authorize(event)) return { status: 'request_failed' };
      diagnostic('captions_ready', { cue_count: captions.body.length });
      step = 'store';
      const result = await serviceRequest(`/api/contest/internal/bilibili-subtitles/${options.materialId}?${query}`,
        { method: 'POST', body: { proof: source.proof, language: track.lan || '', cues: captions.body } });
      return { status: 'ready', segments: result.segments, language: result.language };
    } catch { diagnostic('caption_failed', { step }); return { status: 'request_failed' }; }
    finally { importing = false; }
  }
  return { openLogin, importSubtitles, sessionStatus, observeSessionChanges };
}
module.exports = { allowedUrl, boundedJson, pickSubtitle, createBilibiliBridge };
