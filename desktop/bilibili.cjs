'use strict';

// DeepSteam-owned session bridge. Only caption text crosses into the reading
// store; account cookies never enter the renderer, Python, a model or a log.
// The verified account's display name/avatar may be shown in this local UI.
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
function publicProfile(data) {
  const avatar = typeof data?.face === 'string' ? data.face.replace(/^http:/, 'https:') : '';
  return { displayName: typeof data?.uname === 'string' ? data.uname.slice(0, 80) : '',
    avatarUrl: allowedUrl(avatar, 'hdslb.com') ? avatar : '' };
}
function createBilibiliBridge({ BrowserWindow, getWindow, getSession, authorize, serviceRequest, diagnostic = () => {} }) {
  let loginWindow = null;
  let importing = false;
  let statusRequest = null;
  let sessionEpoch = 0;
  let signingOut = false;
  const listeners = new Set();
  const notify = () => { for (const callback of listeners) callback(); };
  function observeSessionChanges(callback) {
    listeners.add(callback);
    const cookies = getSession().cookies;
    let pending = null;
    const changed = (_event, cookie) => {
      const domain = String(cookie?.domain || '').replace(/^\./, '').toLowerCase();
      if (domain !== 'bilibili.com' && !domain.endsWith('.bilibili.com')) return;
      if (!['SESSDATA', 'DedeUserID', 'bili_jct'].includes(cookie?.name)) return;
      sessionEpoch += 1;
      statusRequest = null;
      clearTimeout(pending);
      pending = setTimeout(() => callback(), 300);
    };
    cookies.on('changed', changed);
    return () => { clearTimeout(pending); listeners.delete(callback); cookies.removeListener('changed', changed); };
  }
  // Electron's Chromium network service rejects a manually supplied Referer
  // header here (ERR_BLOCKED_BY_CLIENT). Keep cookies in the owned session and
  // use the API without that forbidden header; do not weaken browser security.
  const apiHeaders = { Accept: 'application/json', 'User-Agent': 'DeepSteam/ImmersiveReading' };
  async function sessionStatus(event) {
    if (!authorize(event)) return { status: 'denied' };
    if (signingOut) return { status: 'signing_out' };
    const epoch = sessionEpoch;
    if (!statusRequest) {
      const request = Promise.resolve().then(async () => {
        try {
          const response = await getSession().fetch('https://api.bilibili.com/x/web-interface/nav', {
            credentials: 'include', headers: apiHeaders, cache: 'no-store', redirect: 'error',
            signal: AbortSignal.timeout(15000) });
          const body = await boundedJson(response);
          diagnostic('account_response', { http_status: response.status, api_code: Number.isFinite(body.code) ? body.code : null });
          if (body.code === 0 && body.data?.isLogin === true) return { status: 'signed_in', profile: publicProfile(body.data) };
          if (body.code === -101 || body.data?.isLogin === false) return { status: 'signed_out' };
          return { status: 'request_failed' };
        } catch (error) {
          diagnostic('account_failed', { error_kind: ['AbortError', 'TimeoutError', 'TypeError'].includes(error?.name) ? error.name : 'NetworkError' });
          return { status: 'request_failed' };
        }
        finally { if (statusRequest === request) statusRequest = null; }
      });
      statusRequest = request;
    }
    const result = await statusRequest;
    if (epoch !== sessionEpoch) return sessionStatus(event);
    return authorize(event) ? result : { status: 'denied' };
  }
  async function openLogin(event) {
    if (!authorize(event)) return { status: 'denied' };
    if (loginWindow && !loginWindow.isDestroyed()) { loginWindow.show(); loginWindow.focus(); return { status: 'opened' }; }
    loginWindow = new BrowserWindow({ width: 1040, height: 760, title: 'B站登录 - DeepSteam',
      parent: getWindow(), show: true, autoHideMenuBar: true,
      webPreferences: { session: getSession(), sandbox: true, contextIsolation: true,
        nodeIntegration: false, webSecurity: true, allowRunningInsecureContent: false } });
    const ownedWindow = loginWindow;
    let checking = false;
    let loaded = false;
    const checkLogin = async () => {
      if (checking || ownedWindow.isDestroyed()) return;
      checking = true;
      try {
        const result = await sessionStatus(event);
        if (result.status === 'signed_in' && !ownedWindow.isDestroyed()) {
          await getSession().cookies.flushStore();
          diagnostic('login_verified');
          notify();
          ownedWindow.close();
        }
      } finally { checking = false; }
    };
    const showFailure = () => {
      if (ownedWindow.isDestroyed()) return;
      const html = '<!doctype html><meta charset="utf-8"><title>B站登录</title><body style="font:18px system-ui;background:#181714;color:#eee;padding:48px"><h2>B站登录页面连接未完成</h2><p>可以重试。已经完成扫码时，软件仍会继续确认登录状态。</p><p><a style="color:#e4b976" href="https://passport.bilibili.com/login">重新加载 B站登录页</a></p></body>';
      void ownedWindow.loadURL('data:text/html;charset=utf-8,' + encodeURIComponent(html)).catch(() => {});
      notify();
    };
    const loadTimeout = setTimeout(() => {
      if (!loaded && !ownedWindow.isDestroyed()) {
        diagnostic('login_load_timeout');
        ownedWindow.webContents.stop();
        showFailure();
      }
    }, 30000);
    loadTimeout.unref?.();
    const poll = setInterval(() => { void checkLogin(); }, 2500);
    poll.unref?.();
    ownedWindow.webContents.setWindowOpenHandler(({ url }) => {
      if (allowedUrl(url, 'bilibili.com')) void ownedWindow.loadURL(url).catch(() => {});
      return { action: 'deny' };
    });
    ownedWindow.webContents.on('will-navigate', (navigation, url) => {
      if (!allowedUrl(url, 'bilibili.com')) navigation.preventDefault();
    });
    ownedWindow.webContents.on('did-finish-load', () => {
      loaded = true; clearTimeout(loadTimeout); void checkLogin();
    });
    ownedWindow.webContents.on('did-fail-load', (_event, code, _description, _url, main) => {
      if (!main || code === -3 || ownedWindow.isDestroyed()) return;
      diagnostic('login_page_failed', { net_code: Number.isInteger(code) ? code : 0 });
    });
    ownedWindow.on('closed', () => {
      clearTimeout(loadTimeout); clearInterval(poll);
      if (loginWindow === ownedWindow) loginWindow = null;
      notify();
    });
    diagnostic('login_opened');
    // Do not hold the UI's login request until every external page resource has
    // loaded. Account verification is independent and finishes the login flow.
    void ownedWindow.loadURL('https://passport.bilibili.com/login').catch(error => {
      if (error?.errno !== -3 && !ownedWindow.isDestroyed()) showFailure();
    });
    return { status: 'opened' };
  }
  async function signOut(event) {
    if (!authorize(event)) return { status: 'denied' };
    if (signingOut) return { status: 'busy' };
    signingOut = true; sessionEpoch += 1; statusRequest = null;
    try {
      if (loginWindow && !loginWindow.isDestroyed()) loginWindow.close();
      const ownedSession = getSession();
      const cookies = await ownedSession.cookies.get({ domain: 'bilibili.com' });
      for (const cookie of cookies) {
        const domain = String(cookie.domain || '').replace(/^\./, '').toLowerCase();
        if (domain !== 'bilibili.com' && !domain.endsWith('.bilibili.com')) continue;
        const url = (cookie.secure ? 'https://' : 'http://') + domain + (cookie.path || '/');
        await ownedSession.cookies.remove(url, cookie.name);
      }
      await ownedSession.cookies.flushStore();
      const remaining = await ownedSession.cookies.get({ domain: 'bilibili.com' });
      if (remaining.some(c => ['SESSDATA', 'DedeUserID', 'bili_jct'].includes(c.name))) throw new Error('SIGNOUT_INCOMPLETE');
      diagnostic('signed_out');
      return { status: 'signed_out' };
    } catch { diagnostic('signout_failed'); return { status: 'request_failed' }; }
    finally { signingOut = false; sessionEpoch += 1; statusRequest = null; notify(); }
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
  return { openLogin, signOut, importSubtitles, sessionStatus, observeSessionChanges };
}
module.exports = { allowedUrl, boundedJson, pickSubtitle, publicProfile, createBilibiliBridge };
