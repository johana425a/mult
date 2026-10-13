/* Original competition portal. No API keys are stored in browser storage.
 * Modified for DeepSteam on 2026-10-10: plain user-facing names and local/API selection. */
(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const icons = {
    library:'<path d="M4 4h4v16H4zM10 4h4v16h-4zM16 5l3-1 4 15-3 1z"/>',
    book:'<path d="M12 5C9 3 5 3 2 4v15c3-1 7-1 10 1m0-15c3-2 7-2 10-1v15c-3-1-7-1-10 1m0-15v15"/>',
    upload:'<path d="M12 16V3m-5 5 5-5 5 5M4 15v5h16v-5"/>',
    shield:'<path d="m12 3 8 3v5c0 5-4 8-8 10-4-2-8-5-8-10V6zM8 12l3 3 5-6"/>',
    sparkles:'<path d="m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5zM20 2v4m-2-2h4"/>',
    presentation:'<path d="M3 3h18v13H3zM12 16v5m-4 0 4-4 4 4M7 12l3-3 3 2 4-5"/>',
    pen:'<path d="m14 5 5 5M4 20l4-1L21 6a2 2 0 0 0-5-3L3 16l-1 5zM12 21h9"/>',
    thought:'<path d="M7 15c-2-2-3-4-2-7a7 7 0 0 1 14 1c0 3-1 4-3 6l-1 2H8zM9 20h5M12 4V1M3 5 1 3m20 2 2-2M9 10l2 2 4-4"/>',
    play:'<path d="m8 4 12 8-12 8z"/>',
    info:'<circle cx="12" cy="12" r="9"/><path d="M12 11v6m0-10v1"/>',
    check:'<path d="m5 12 4 4L19 6"/>',
    refresh:'<path d="M20 7a8 8 0 1 0 1 8M20 3v5h-5"/>',
    grid:'<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
    sliders:'<path d="M5 3v7m0 5v6M12 3v12m0 5v1M19 3v2m0 5v11M2 10h6m1 5h6m1-10h6"/>',
    file:'<path d="M5 3h9l5 5v13H5zM14 3v6h5M8 13h8m-8 4h6"/>',
    clock:'<circle cx="12" cy="12" r="9"/><path d="M12 6v6l4 2"/>',
    alert:'<path d="m12 3 10 18H2zM12 9v5m0 3v1"/>',
    arrow:'<path d="M5 12h14m-5-5 5 5-5 5"/>'
  };
  const icon = (name) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${icons[name] || icons.file}</svg>`;
  document.querySelectorAll('[data-icon]').forEach((el) => { el.innerHTML = icon(el.dataset.icon); });
  const escapeHTML = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  // A small safe reader: only explicit text formatting, no HTML or remote media execution.
  function renderMarkdownText(text) {
    const lines = String(text).split(/\r?\n/), blocks = [];
    const inline = (value) => escapeHTML(value).replace(/\*\*([^*]+)\*\*/g,'<strong>$1</strong>').replace(/`([^`]+)`/g,'<code>$1</code>');
    for (let index = 0; index < lines.length; index++) {
      const line = lines[index];
      if (!line.trim()) continue;
      const heading = line.match(/^(#{1,6})\s+(.+)/);
      if (heading) { const level = Math.min(heading[1].length + 2,6); blocks.push(`<h${level}>${inline(heading[2])}</h${level}>`); continue; }
      if (line.trim().startsWith('|') && /^\s*\|?[\s:|-]+\|\s*$/.test(lines[index + 1] || '')) {
        const cells = (row) => row.trim().replace(/^\|/,'').replace(/\|$/,'').split('|').map((cell) => inline(cell.trim()));
        const headers = cells(line); index += 2; const rows = [];
        while (index < lines.length && lines[index].trim().startsWith('|')) { rows.push(`<tr>${cells(lines[index]).map((cell) => `<td>${cell}</td>`).join('')}</tr>`); index++; }
        index--; blocks.push(`<div class="source-table-wrap"><table><thead><tr>${headers.map((cell) => `<th>${cell}</th>`).join('')}</tr></thead><tbody>${rows.join('')}</tbody></table></div>`); continue;
      }
      blocks.push(`<p>${inline(line)}</p>`);
    }
    return blocks.join('');
  }
  const state = {materials:[],lessons:[],attempts:[],selectedMaterial:null,selectedLesson:null,settings:null,materialConfig:null,lessonPoll:null,attemptPoll:null,lessonSubmitting:false,attemptSubmitting:false,materialLoading:false,view:'workspace'};
  let toastTimer;
  const formatDate = (date, full = false) => {
    if (!date) return 'Time not recorded';
    const value = new Date(date);
    if (Number.isNaN(value.getTime())) return String(date);
    return new Intl.DateTimeFormat('en', full ? {year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'} : {month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}).format(value);
  };
  const appHosts = {'3791':'portal', '3792':'app', '3793':'classroom', '3794':'gateway'};
  const safeURL = (value) => {
    if (typeof value !== 'string' || !value.trim()) return null;
    try {
      const url = new URL(value, location.href);
      if (url.username || url.password) return null;
      if (url.protocol === 'deepsteam:') return ['app','portal','classroom','gateway'].includes(url.hostname) && !url.port ? url.href : null;
      if (!['http:','https:'].includes(url.protocol)) return null;
      if (location.protocol === 'deepsteam:' && url.protocol === 'http:' && ['127.0.0.1','localhost'].includes(url.hostname) && appHosts[url.port])
        return `deepsteam://${appHosts[url.port]}${url.pathname}${url.search}${url.hash}`;
      return url.href;
    } catch (_) { return null; }
  };
  const publicError = (value) => String(value ?? '').replace(/https?:\/\/(?:127\.0\.0\.1|localhost):(?:379[1-6]|8011)(?=[/\s"'?#]|$)[^\s"'<>]*/gi, 'DeepSteam internal service');
  if (location.protocol === 'deepsteam:') {
    const entries = {learning:'deepsteam://app/chat', settings:'deepsteam://app/settings', classroom:'deepsteam://classroom/'};
    document.querySelectorAll('a[href^="/open/"]').forEach((anchor) => { const target = entries[anchor.getAttribute('href').slice('/open/'.length)]; if (target) anchor.href = target; });
  }
  const isPending = (status) => ['queued','pending','generating','grading','running','processing','submitted','starting','in_progress'].includes(String(status || '').toLowerCase());
  const isError = (status) => ['failed','error','interrupted','cancelled','canceled'].includes(String(status || '').toLowerCase());
  const isAwaiting = (status) => status === 'awaiting_reconnect';
  const isReviewDraft = (lesson) => lesson?.status === 'failed' && Boolean(lesson.review_required) && lesson.source_fidelity === 'needs_review' && /^[a-zA-Z0-9_-]+$/.test(lesson.classroom_id || '') && Boolean(safeURL(lesson.classroom_url));
  const statusLabel = (lesson) => isReviewDraft(lesson) ? 'Generation failed · Review draft' : isAwaiting(lesson.status) ? 'Awaiting a status check' : isError(lesson.status) ? 'Generation incomplete' : isPending(lesson.status) ? 'Generating' : lesson.classroom_url ? 'Classroom ready' : ['completed','ready','success','done'].includes(lesson.status) ? 'Complete' : 'Saved';
  function toast(message, error = false) { clearTimeout(toastTimer); $('toast').textContent = message; $('toast').classList.toggle('error', error); $('toast').classList.remove('leaving'); $('toast').hidden = false; toastTimer = setTimeout(() => { $('toast').classList.add('leaving'); toastTimer = setTimeout(() => { $('toast').hidden = true; $('toast').classList.remove('leaving'); }, 260); }, error ? 6500 : 3600); }
  function renderErrorDetails(error) { return error ? `<details class="error-details"><summary>View error details</summary><pre class="record-block" style="white-space:pre-wrap;overflow-wrap:anywhere;max-height:16rem;overflow:auto">${escapeHTML(publicError(error.message || error))}</pre></details>` : ''; }
  function showError(id, error) { const el = $(id); el.innerHTML = error ? `<div><p>This operation is unfinished. Check your input or try again shortly.</p>${renderErrorDetails(error)}</div>` : ''; el.hidden = !error; }
  function busy(id, value) { $(id).disabled = value; $(id).classList.toggle('is-loading', value); }
  async function api(path, options = {}) {
    let response;
    try { response = await fetch(path, {...options, headers:{...(options.body instanceof FormData ? {} : {'Content-Type':'application/json'}), ...options.headers}}); }
    catch (_) { throw new Error('Could not connect to the local workbench. Check that its services are running, then retry.'); }
    let result;
    const text = await response.text();
    try { result = text ? JSON.parse(text) : {}; } catch (_) { throw new Error(`The service returned unreadable content (HTTP ${response.status}). Check the local service logs.`); }
    if (!response.ok) {
      const detail = result.detail || result.error || result.message;
      throw new Error(typeof detail === 'string' ? detail : detail ? JSON.stringify(detail) : `Operation failed (HTTP ${response.status}). Try again shortly.`);
    }
    return result;
  }
  function upsert(items, item) { const index = items.findIndex((entry) => entry.id === item.id); if (index === -1) items.unshift(item); else items[index] = {...items[index],...item}; }
  function syncCounts() { $('materials-count').textContent = state.materials.length; $('attempts-count').textContent = state.attempts.length; $('lessons-count').textContent = state.lessons.length; $('records-count').textContent = state.attempts.length; $('records-count').hidden = !state.attempts.length; $('workspace-counts').textContent = `${state.materials.length} materials · ${state.lessons.length} lessons · ${state.attempts.length} attempts`; }
  function syncSubmitButtons() { $('generate-lesson').disabled = !state.selectedMaterial || state.materialLoading || state.lessonSubmitting || !$('lesson-goal').value.trim(); $('submit-attempt').disabled = state.attemptSubmitting || !$('practice-lesson').value || !$('attempt-question').value.trim() || !$('attempt-answer').value.trim(); }

  async function refreshStatus() {
    try {
      const result = await api('/api/status');
      for (const name of ['deeptutor','openmaic']) {
        const service = result.services?.[name];
        $(`${name}-state`).textContent = service?.ok ? 'Running' : 'Not running';
        $(`${name}-dot`).className = `status-dot${service?.ok ? '' : ' offline'}`;
        $(`${name}-link`).title = service?.ok ? 'Open learning space' : 'The service is not running. Launch DeepSteam first.';
      }
      showError('connection-alert', null);
    } catch (error) { for (const name of ['deeptutor','openmaic']) { $(`${name}-state`).textContent = 'Status unknown'; $(`${name}-dot`).className = 'status-dot unknown'; } showError('connection-alert', error); }
  }
  async function refreshMaterials() {
    const result = await api('/api/materials'); state.materials = result.items || []; renderMaterials(); syncCounts();
    if (state.selectedMaterial && !state.materials.some((item) => item.id === state.selectedMaterial.id)) { state.selectedMaterial = null; renderSelectedMaterial(); }
  }
  function renderMaterials() {
    $('materials-list').innerHTML = state.materials.length ? state.materials.map((item) => `<button type="button" class="material-item${state.selectedMaterial?.id === item.id ? ' selected' : ''}" data-material-id="${escapeHTML(item.id)}" aria-pressed="${state.selectedMaterial?.id === item.id}"><span class="file-icon">${icon('file')}</span><span class="material-item-body"><strong title="${escapeHTML(item.title || item.filename)}">${escapeHTML(item.title || item.filename)}</strong><small>${escapeHTML((item.filename || '').split('.').pop().toUpperCase())} · ${escapeHTML(formatDate(item.created_at))}</small></span>${state.selectedMaterial?.id === item.id ? '<span class="selected-mark">✓</span>' : ''}</button>`).join('') : '<div class="empty-list">No course materials yet<br>Upload your first document above</div>';
  }
  function renderSelectedMaterial() {
    const item = state.selectedMaterial;
    $('reading-empty').hidden = !!item; $('reading-content').hidden = !item; $('material-format').hidden = !item; $('material-original').hidden = !item;
    if (item) {
      $('material-title').textContent = item.title || item.filename; $('material-original').href = `/api/materials/${encodeURIComponent(item.id)}/file`;
      $('material-details').textContent = `${item.filename || 'Course materials'} · ${Number(item.char_count || 0).toLocaleString('en')} characters · ${formatDate(item.created_at)}`;
      $('material-format').textContent = (item.filename || 'TEXT').split('.').pop().toUpperCase();
      const content = item.text || item.content || item.text_preview || '';
      $('material-preview').classList.toggle('formatted-source', /\.md$/i.test(item.filename || ''));
      if (/\.md$/i.test(item.filename || '') && content) $('material-preview').innerHTML = renderMarkdownText(content);
      else $('material-preview').textContent = content || 'No preview text was extracted. For a scanned PDF, check the configured document parsing service.';
      $('material-text-note').textContent = item.warning || item.text_note || (content.length < Number(item.char_count || 0) ? 'This is a text preview. Classroom generation uses the material saved locally.' : 'The original material remains local. This is an extracted text preview; the visual classroom opens after generation.');
    }
    renderMaterials(); renderRecentLessons(); syncSubmitButtons();
  }
  async function selectMaterial(id) {
    const item = state.materials.find((entry) => entry.id === id); if (!item) return;
    state.selectedMaterial = item; state.materialLoading = true; renderSelectedMaterial();
    try { const detail = await api(`/api/materials/${encodeURIComponent(id)}`); if (state.selectedMaterial?.id !== id) return; state.selectedMaterial = {...item,...detail}; upsert(state.materials, state.selectedMaterial); }
    catch (error) { toast(error.message, true); }
    finally { if (state.selectedMaterial?.id === id) { state.materialLoading = false; renderSelectedMaterial(); } }
    if (state.selectedMaterial?.id === id) { const latest = state.lessons.find((lesson) => lesson.material_id === id); if (latest) selectLesson(latest.id); else { clearTimeout(state.lessonPoll); state.selectedLesson = null; $('lesson-result').hidden = true; $('practice-lesson').value = ''; syncSubmitButtons(); } }
  }
  async function uploadFile(file) {
    if (!file) return;
    if (!state.materialConfig) {
      try { state.materialConfig = await api('/api/material-config'); }
      catch (error) { showError('upload-error', error); return; }
    }
    const suffix = '.' + file.name.split('.').pop().toLowerCase();
    if (!state.materialConfig.extensions.includes(suffix)) { showError('upload-error', 'Choose a supported document.'); return; }
    if (!file.size || file.size > state.materialConfig.max_bytes) { showError('upload-error', `The material must be nonempty and no larger than ${Math.floor(state.materialConfig.max_bytes / 1024 / 1024)} MB.`); return; }
    showError('upload-error', null); $('upload-zone').classList.add('busy'); $('upload-title').textContent = 'Saving and reading...';
    try { const form = new FormData(); form.append('file', file); const item = await api('/api/materials', {method:'POST',body:form}); upsert(state.materials,item); syncCounts(); await selectMaterial(item.id); toast('Materials saved locally'); }
    catch (error) { showError('upload-error', error); }
    finally { $('upload-zone').classList.remove('busy'); $('upload-title').textContent = 'Upload your materials'; $('material-file').value = ''; }
  }
  async function importDemo() {
    busy('import-demo',true);
    try { const item = await api('/api/demo-material',{method:'POST'}); upsert(state.materials,item); syncCounts(); await selectMaterial(item.id); if (!$('lesson-goal').value.trim()) $('lesson-goal').value = 'I am new to this topic. Use examples from the materials, clear visual explanations, and interactive questions to help me understand key concepts and reasoning.'; syncSubmitButtons(); toast('Demo materials imported; no classroom model call was made'); }
    catch (error) { toast(error.message,true); }
    finally { busy('import-demo',false); }
  }
  async function openDemoLesson() {
    busy('open-demo-lesson',true);
    try {
      const lesson = await api('/api/demo-lesson',{method:'POST',body:JSON.stringify({})});
      upsert(state.lessons,lesson); await refreshMaterials();
      if (lesson.material_id) await selectMaterial(lesson.material_id);
      selectLesson(lesson.id); renderRecentLessons(); renderHistoryLessons(); syncCounts();
      $('lesson-result').scrollIntoView({behavior:'smooth',block:'center'});
      toast('Prepared demo classroom opened; no model was called');
    } catch (error) { toast(error.message,true); }
    finally { busy('open-demo-lesson',false); }
  }
  function lessonWarnings(lesson) {
    let coverage = lesson.tts_coverage;
    if (typeof coverage === 'string') { try { coverage = JSON.parse(coverage); } catch (_) { coverage = null; } }
    const validCoverage = coverage && Number.isFinite(Number(coverage.written)) && Number.isFinite(Number(coverage.total));
    return `${lesson.warning ? `<div class="lesson-warning">${icon('alert')}<p>${escapeHTML(lesson.warning)}</p></div>` : ''}${validCoverage ? `<p class="audio-coverage">Narration coverage: ${escapeHTML(coverage.written)} / ${escapeHTML(coverage.total)}${Number(coverage.written) < Number(coverage.total) ? ' · Not fully complete' : ''}</p>` : ''}`;
  }

  async function refreshLessons() { const result = await api('/api/lessons'); state.lessons = result.items || []; renderRecentLessons(); renderPracticeSelect(); renderHistoryLessons(); syncCounts(); }
  function renderRecentLessons() {
    const items = state.lessons.filter((item) => item.material_id === state.selectedMaterial?.id);
    $('recent-lessons-wrap').hidden = !items.length;
    $('recent-lessons-list').innerHTML = items.slice(0,5).map((item) => `<button class="lesson-row" type="button" data-lesson-id="${escapeHTML(item.id)}"><span class="lesson-row-title">${escapeHTML(item.title || 'Untitled classroom')}</span><span class="status-label${isPending(item.status) || isAwaiting(item.status) ? ' pending' : isError(item.status) ? ' error' : ''}">${statusLabel(item)}</span></button>`).join('');
  }
  function renderPracticeSelect() {
    const previous = $('practice-lesson').value;
    $('practice-lesson').innerHTML = '<option value="">Choose a saved lesson</option>' + state.lessons.map((lesson) => `<option value="${escapeHTML(lesson.id)}">${escapeHTML(lesson.title || 'Untitled classroom')}${isPending(lesson.status) ? ' · Generating' : isError(lesson.status) ? ' · Generation incomplete' : ''}</option>`).join('');
    $('practice-lesson').value = state.lessons.some((item) => item.id === previous) ? previous : state.selectedLesson?.id || '';
    syncSubmitButtons();
  }
  function renderLessonResult() {
    const lesson = state.selectedLesson; if (!lesson) { $('lesson-result').hidden = true; return; }
    const pending = isPending(lesson.status), awaiting = isAwaiting(lesson.status), error = isError(lesson.status), review = isReviewDraft(lesson), url = safeURL(lesson.classroom_url);
    $('lesson-result').hidden = false; $('lesson-result').classList.toggle('error',error);
    const heading = review ? 'Generation failed · Review draft' : awaiting ? 'Original task preserved, awaiting a status check' : error ? 'This classroom has not finished generating' : pending ? 'Preparing your interactive classroom' : url ? 'Classroom ready' : 'Classroom task saved';
    const detail = review ? lesson.progress || 'The draft was preserved but source verification has not passed. Review it against the source; narration and video have not been generated automatically.' : awaiting ? lesson.progress || 'Completion of the original task is not confirmed. Continue checking only queries that task and does not regenerate.' : error ? 'The classroom task is unfinished. Check the model and classroom service settings or retry shortly.' : pending ? lesson.progress_message || lesson.progress || lesson.message || 'The configured service is generating the classroom. You can keep reading; progress updates automatically.' : lesson.progress || (url ? 'Explore slides, explanations, and questions in the classroom, or export a teaching video.' : 'The task returned without a classroom link. Refresh the records or check the task in the classroom center.');
    const actions = review ? `<div class="result-actions"><a class="button button-secondary button-small" href="${escapeHTML(url)}" target="_blank" rel="noopener noreferrer">View review draft ${icon('arrow')}</a></div>` : awaiting && lesson.job_id ? '<div class="result-actions"><button class="button button-primary button-small" id="resume-lesson" type="button">Continue checking original task</button></div>' : url && !error ? `<div class="result-actions"><a class="button button-primary button-small" href="${escapeHTML(url)}" target="_blank" rel="noopener noreferrer">Open classroom ${icon('arrow')}</a><button class="button button-secondary button-small" id="embed-classroom" type="button">Preview here</button></div>` : error ? '<div class="result-actions"><a class="button button-secondary button-small" href="#settings">Check API settings</a><button class="text-button" id="retry-lesson" type="button">Restore original goal and regenerate →</button></div>' : '';
    $('lesson-result').innerHTML = `<div class="result-heading${error ? ' error' : ''}">${pending ? '<span class="spinner" aria-hidden="true"></span>' : icon(error || awaiting ? 'alert' : 'check')}<span>${heading}</span></div><p class="result-detail">${escapeHTML(detail)}</p>${lessonWarnings(lesson)}${renderErrorDetails(lesson.error)}${actions}<p class="result-note">${escapeHTML(lesson.title || 'Untitled classroom')} · ${escapeHTML(formatDate(lesson.created_at))}</p><div id="classroom-embed-slot"></div>`;
  }
  async function resumeLesson() {
    const lesson = state.selectedLesson; if (!lesson?.job_id || !isAwaiting(lesson.status)) return;
    busy('resume-lesson',true);
    try { const item = await api(`/api/lessons/${encodeURIComponent(lesson.id)}/resume`,{method:'POST'}); upsert(state.lessons,item); if (state.selectedLesson?.id === lesson.id) { state.selectedLesson = {...lesson,...item}; renderLessonResult(); scheduleLessonPoll(lesson.id,1000); } toast('Continued checking the original task; no new generation job was created'); }
    catch (error) { toast(error.message,true); }
    finally { if ($('resume-lesson')) busy('resume-lesson',false); }
  }
  function selectLesson(id) { const lesson = state.lessons.find((item) => item.id === id); if (!lesson) return; clearTimeout(state.lessonPoll); state.selectedLesson = lesson; renderLessonResult(); renderPracticeSelect(); $('practice-lesson').value = lesson.id; syncSubmitButtons(); if (isPending(lesson.status)) scheduleLessonPoll(id); }
  function scheduleLessonPoll(id, delay = 3000) {
    clearTimeout(state.lessonPoll);
    state.lessonPoll = setTimeout(async () => {
      if (state.selectedLesson?.id !== id) return;
      try { const item = await api(`/api/lessons/${encodeURIComponent(id)}`); upsert(state.lessons,item); if (state.selectedLesson?.id !== id) return; state.selectedLesson = {...state.selectedLesson,...item}; renderLessonResult(); renderRecentLessons(); renderHistoryLessons(); renderPracticeSelect(); if (isPending(item.status)) scheduleLessonPoll(id); else { syncCounts(); toast(isError(item.status) ? 'Classroom generation is incomplete. View the details.' : 'Classroom task updated',isError(item.status)); } }
      catch (error) { if (state.selectedLesson?.id === id) { const detail = $('lesson-result').querySelector('.result-detail'); if (detail) detail.textContent = 'The classroom service is temporarily unavailable. The original task was preserved; waiting to reconnect without resubmitting.'; const previous = $('lesson-result').querySelector('[data-poll-error]'); if (previous) previous.remove(); $('lesson-result').insertAdjacentHTML('beforeend', `<div data-poll-error>${renderErrorDetails(error)}</div>`); scheduleLessonPoll(id,8000); } }
    },delay);
  }
  async function generateLesson(event) {
    event.preventDefault(); if (state.lessonSubmitting || !state.selectedMaterial || !$('lesson-goal').value.trim()) return;
    state.lessonSubmitting = true; busy('generate-lesson',true); showError('lesson-error',null);
    try { const item = await api('/api/lessons',{method:'POST',body:JSON.stringify({material_id:state.selectedMaterial.id,title:$('lesson-title').value.trim() || state.selectedMaterial.title || 'Interactive classroom',goal:$('lesson-goal').value.trim()})}); upsert(state.lessons,item); selectLesson(item.id); renderRecentLessons(); renderHistoryLessons(); syncCounts(); toast('Classroom task submitted'); }
    catch (error) { showError('lesson-error',error); }
    finally { state.lessonSubmitting = false; busy('generate-lesson',false); syncSubmitButtons(); }
  }

  async function refreshAttempts() { const result = await api('/api/attempts'); state.attempts = result.items || []; renderAttempts(); syncCounts(); }
  function feedbackText(value) { return typeof value === 'string' ? value : value && typeof value === 'object' ? value.text || value.feedback || JSON.stringify(value,null,2) : ''; }
  function renderAttemptResult(item) { const pending = isPending(item.status), error = isError(item.status) || !!item.error; $('attempt-result').hidden = false; $('attempt-result').innerHTML = `<h3>${pending ? 'Answer saved; generating feedback' : error ? 'Answer saved; feedback unfinished' : 'Learning feedback'}</h3><p>${escapeHTML(item.error ? 'Your answer was saved. Feedback is unfinished; retry later.' : feedbackText(item.feedback) || (pending ? 'Please wait. Your answer is available in learning records.' : 'Your answer was saved, but feedback has not returned yet.'))}</p>${renderErrorDetails(item.error)}`; }
  async function submitAttempt(event) {
    event.preventDefault(); const lessonId = $('practice-lesson').value, answer = $('attempt-answer').value.trim(), question = $('attempt-question').value.trim(); if (!lessonId || !answer || !question || state.attemptSubmitting) return;
    state.attemptSubmitting = true; busy('submit-attempt',true); showError('attempt-error',null);
    try { const result = await api(`/api/lessons/${encodeURIComponent(lessonId)}/attempts`,{method:'POST',body:JSON.stringify({answer,question})}); const item = {lesson_id:lessonId,lesson_title:state.lessons.find((lesson) => lesson.id === lessonId)?.title,question,answer,...result}; upsert(state.attempts,item); renderAttempts(); renderAttemptResult(item); syncCounts(); toast(isError(item.status) ? 'Answer saved. Check the feedback status.' : 'Answer saved'); if (isPending(item.status)) scheduleAttemptPoll(item.id); }
    catch (error) { showError('attempt-error',error); }
    finally { state.attemptSubmitting = false; busy('submit-attempt',false); syncSubmitButtons(); }
  }
  function scheduleAttemptPoll(id, delay = 3500) { clearTimeout(state.attemptPoll); state.attemptPoll = setTimeout(async () => { try { await refreshAttempts(); const item = state.attempts.find((entry) => entry.id === id); if (item) { renderAttemptResult(item); if (isPending(item.status)) scheduleAttemptPoll(id); } } catch (_) { scheduleAttemptPoll(id,8000); } },delay); }
  function renderAttempts() {
    $('attempts-list').innerHTML = state.attempts.length ? state.attempts.map((item) => `<article class="record-card"><div class="record-card-meta"><span>${escapeHTML(item.lesson_title || state.lessons.find((lesson) => lesson.id === item.lesson_id)?.title || 'Classroom answer')}</span><time>${escapeHTML(formatDate(item.created_at,true))}</time></div><h3>${escapeHTML(item.question || 'Learning reflection')}</h3><div class="record-block"><strong>My original answer</strong>${escapeHTML(item.answer || item.user_answer || 'Answer text not returned')}</div>${item.error ? `<p class="result-note">Your answer was saved; feedback is unfinished.</p>${renderErrorDetails(item.error)}` : item.feedback ? `<details><summary>Show learning feedback</summary><div class="record-block feedback">${escapeHTML(feedbackText(item.feedback))}</div></details>` : `<p class="result-note">${isPending(item.status) ? 'Generating feedback' : 'Your answer was saved; no feedback yet'}</p>`}</article>`).join('') : `<div class="records-empty">${icon('pen')}<h3>Your learning journal starts with your first answer</h3><p>Submit an answer in the workbench, <br>and its question, original answer, and feedback are saved here.</p><a href="#workspace" class="text-button">Back to the workbench →</a></div>`;
  }
  function renderHistoryLessons() {
    $('all-lessons-list').innerHTML = state.lessons.length ? state.lessons.map((item) => `<article class="history-lesson"><div class="history-lesson-top"><h3>${escapeHTML(item.title || 'Untitled classroom')}</h3><span class="status-label${isPending(item.status) || isAwaiting(item.status) ? ' pending' : isError(item.status) ? ' error' : ''}">${statusLabel(item)}</span></div><p>${escapeHTML(item.goal || '')}<br>${escapeHTML(formatDate(item.created_at,true))}</p>${lessonWarnings(item)}<button type="button" class="text-button" data-history-lesson="${escapeHTML(item.id)}">${isReviewDraft(item) ? 'View review draft details' : isAwaiting(item.status) ? 'View and continue checking original task' : item.classroom_url && !isError(item.status) ? 'Return to classroom and practice' : 'View task details'} →</button></article>`).join('') : `<div class="records-empty">${icon('presentation')}<h3>No classrooms yet</h3><p>Choose materials and a learning goal, <br>then create your first interactive classroom.</p></div>`;
  }

  async function refreshSettings() {
    const result = await api('/api/settings'); state.settings = result;
    $('setting-base-url').value = result.base_url || ''; $('setting-model').value = result.model || ''; $('setting-api-key').value = ''; $('setting-tts-key').value = ''; $('clear-api-key').checked = false; $('clear-tts-key').checked = false;
    $('setting-tts-enabled').checked = !!result.tts_enabled;
    $('setting-tts-mode').value = result.tts_mode || 'local'; syncTtsFields();
    $('setting-tts-url').value = result.tts_base_url || ''; $('setting-tts-model').value = result.tts_model || ''; $('setting-tts-voice').value = result.tts_voice || '';
    $('api-key-status').textContent = result.api_key_set ? 'Saved · Leave blank to keep' : 'Not set'; $('tts-key-status').textContent = result.tts_key_set ? 'Saved · Leave blank to keep' : 'Not set';
    $('setting-model-mode').value = result.connection_mode || 'unconfigured';
    syncModelFields();
    const managed = ['native', 'current'].includes($('setting-model-mode').value);
    $('settings-state').textContent = managed ? 'Using your selected model connection' : result.base_url && result.model ? 'API settings saved · Verified when called' : 'No model connection configured';
    $('model-setup-notice').hidden = managed || !!(result.base_url && result.model);
  }
  async function saveSettings(event) {
    event.preventDefault(); showError('settings-error',null);
    const body = {connection_mode:$('setting-model-mode').value,model_mode:'api',tts_enabled:$('setting-tts-enabled').checked,tts_mode:$('setting-tts-mode').value,tts_base_url:$('setting-tts-url').value.trim(),tts_model:$('setting-tts-model').value.trim(),tts_voice:$('setting-tts-voice').value.trim()};
    if (body.connection_mode === 'custom') {
      body.base_url = $('setting-base-url').value.trim();
      body.model = $('setting-model').value.trim();
      if ((body.base_url && !body.model) || (body.model && !body.base_url)) { showError('settings-error','Enter both the model Base URL and model name.'); return; }
      if ($('setting-api-key').value.trim()) body.api_key = $('setting-api-key').value.trim();
      if ($('clear-api-key').checked) body.clear_api_key = true;
    }
    if (body.tts_enabled && body.tts_mode === 'api' && (!body.tts_base_url || !body.tts_model || !body.tts_voice)) { showError('settings-error','Enter the TTS Base URL, speech model, and voice before enabling API narration.'); return; }
    if ($('setting-tts-key').value.trim()) body.tts_api_key = $('setting-tts-key').value.trim();
    if ($('clear-tts-key').checked) body.clear_tts_api_key = true;
    if (body.clear_api_key && body.api_key || body.clear_tts_api_key && body.tts_api_key) { showError('settings-error','Choose either entering a new key or clearing the saved key.'); return; }
    busy('save-settings',true);
    try { await api('/api/settings',{method:'PUT',body:JSON.stringify(body)}); await refreshSettings(); toast('Settings saved; availability is verified when called'); }
    catch (error) { showError('settings-error',error); }
    finally { busy('save-settings',false); }
  }
  function switchView() {
    const view = location.hash.replace('#','') || 'workspace'; state.view = ['workspace','records','settings'].includes(view) ? view : 'workspace';
    ['workspace','records','settings'].forEach((name) => { $(`view-${name}`).hidden = name !== state.view; document.querySelector(`[data-view="${name}"]`).classList.toggle('active',name === state.view); if (name === state.view) document.querySelector(`[data-view="${name}"]`).setAttribute('aria-current','page'); else document.querySelector(`[data-view="${name}"]`).removeAttribute('aria-current'); });
    if (state.view === 'records') Promise.all([refreshLessons(),refreshAttempts()]).catch((error) => toast(error.message,true));
  }

  $('material-file').addEventListener('change',(event) => uploadFile(event.target.files[0]));
  $('choose-file-empty').addEventListener('click',() => $('material-file').click());
  $('upload-zone').addEventListener('keydown',(event) => { if (['Enter',' '].includes(event.key)) { event.preventDefault(); $('material-file').click(); } });
  ['dragenter','dragover'].forEach((name) => $('upload-zone').addEventListener(name,(event) => { event.preventDefault(); $('upload-zone').classList.add('dragging'); }));
  ['dragleave','drop'].forEach((name) => $('upload-zone').addEventListener(name,(event) => { event.preventDefault(); $('upload-zone').classList.remove('dragging'); }));
  $('upload-zone').addEventListener('drop',(event) => { if (!$('upload-zone').classList.contains('busy')) uploadFile(event.dataTransfer.files[0]); });
  $('import-demo').addEventListener('click',importDemo);
  $('open-demo-lesson').addEventListener('click',openDemoLesson);
  $('lesson-result').addEventListener('click',(event) => { if (event.target.closest('#resume-lesson')) resumeLesson(); });
  $('materials-list').addEventListener('click',(event) => { const item = event.target.closest('[data-material-id]'); if (item) selectMaterial(item.dataset.materialId); });
  $('recent-lessons-list').addEventListener('click',(event) => { const item = event.target.closest('[data-lesson-id]'); if (item) selectLesson(item.dataset.lessonId); });
  $('all-lessons-list').addEventListener('click',async (event) => { const item = event.target.closest('[data-history-lesson]'); if (!item) return; const lesson = state.lessons.find((entry) => entry.id === item.dataset.historyLesson); location.hash = 'workspace'; if (lesson?.material_id && state.selectedMaterial?.id !== lesson.material_id) await selectMaterial(lesson.material_id); selectLesson(lesson.id); $('lesson-result').scrollIntoView({behavior:'smooth',block:'center'}); });
  $('lesson-result').addEventListener('click',(event) => { if (event.target.closest('#embed-classroom')) { const url = safeURL(state.selectedLesson?.classroom_url); if (!url) return; $('classroom-embed-slot').innerHTML = `<p class="frame-note">If the embedded classroom does not appear, use Open classroom above to open it separately.</p><iframe class="classroom-frame" src="${escapeHTML(url)}" title="Interactive classroom preview" allow="microphone; autoplay; fullscreen" loading="lazy" referrerpolicy="same-origin"></iframe>`; $('embed-classroom').hidden = true; } if (event.target.closest('#retry-lesson')) { $('lesson-goal').value = state.selectedLesson?.goal || ''; $('lesson-title').value = state.selectedLesson?.title || ''; $('lesson-goal').focus(); syncSubmitButtons(); } });
  $('lesson-form').addEventListener('submit',generateLesson); $('attempt-form').addEventListener('submit',submitAttempt); $('settings-form').addEventListener('submit',saveSettings);
  ['lesson-goal','attempt-question','attempt-answer','practice-lesson'].forEach((id) => $(id).addEventListener('input',syncSubmitButtons));
  function syncTtsFields() { const local = $('setting-tts-mode').value === 'local'; $('tts-fields').hidden = local; $('tts-fields').disabled = local || !$('setting-tts-enabled').checked; $('local-tts-note').hidden = !local; }
  $('setting-tts-enabled').addEventListener('change',syncTtsFields);
  $('setting-tts-mode').addEventListener('change',syncTtsFields);
  function syncModelFields() {
    const custom = $('setting-model-mode').value === 'custom';
    $('local-model-note').hidden = !['native', 'current'].includes($('setting-model-mode').value);
    for (const id of ['setting-base-url', 'setting-model', 'setting-api-key', 'clear-api-key']) {
      $(id).disabled = !custom;
      if (!custom && id !== 'clear-api-key') $(id).value = '';
    }
  }
  $('setting-model-mode').addEventListener('change',syncModelFields);
  $('refresh-status').addEventListener('click',refreshStatus); $('refresh-lessons').addEventListener('click',() => refreshLessons().catch((error) => toast(error.message,true)));
  $('refresh-records').addEventListener('click',async () => { busy('refresh-records',true); try { await Promise.all([refreshLessons(),refreshAttempts()]); toast('Learning records refreshed'); } catch (error) { toast(error.message,true); } finally { busy('refresh-records',false); } });
  window.addEventListener('hashchange',switchView);
  document.addEventListener('visibilitychange',() => { if (!document.hidden) refreshStatus(); });
  async function initialize() {
    switchView();
    refreshStatus(); // An offline engine must not delay local reading and saved records.
    const results = await Promise.allSettled([refreshMaterials(),refreshLessons(),refreshAttempts(),refreshSettings()]);
    const failed = results.filter((item) => item.status === 'rejected');
    if (failed.length) { showError('connection-alert',failed[0].reason); if (results[0].status === 'rejected') $('materials-list').innerHTML = '<div class="empty-list">Materials could not be loaded<br>Check the local services and refresh</div>'; if (results[3].status === 'rejected') $('settings-state').textContent = 'Settings could not be loaded. Refresh and retry.'; }
    if (state.materials.length) await selectMaterial(state.materials[0].id);
    syncSubmitButtons();
  }
  initialize();
})();
