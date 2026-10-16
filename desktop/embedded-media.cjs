'use strict';
const {PRESENTATION}=require('./bilibili-presentation.cjs');
// Exchange only playback state with the app's official player frame. No
// cookies, account identity, page text or media URL crosses this bridge.
const SNAPSHOT = `(() => {
  ${PRESENTATION}
  const media = [...document.querySelectorAll('video,bwp-video')]
    .find(node => Number.isFinite(Number(node.currentTime)) && Number(node.readyState) >= 1);
  if (!media) return {status:'waiting'};
  return {status:'ready',time:Number(media.currentTime),duration:Number(media.duration),
    paused:Boolean(media.paused),ended:Boolean(media.ended),rate:Number(media.playbackRate),
    readyState:Number(media.readyState)};
})()`;
function matchingFrame(frame, options) {
  try {
    const url = new URL(frame.url);
    return url.protocol === 'https:' && url.hostname === 'player.bilibili.com'
      && (!url.port || url.port === '443') && !url.username && !url.password
      && url.pathname === '/player.html' && url.searchParams.get('bvid') === options.bvid
      && Number(url.searchParams.get('p') || 1) === options.page;
  } catch { return false; }
}
function cleanState(value) {
  if (value?.status !== 'ready') return {status:'waiting'};
  const {time,duration,rate,readyState}=value;
  if (![time,duration,rate,readyState].every(Number.isFinite) || time < 0 || duration <= 0
      || time > duration + 2 || duration > 604800 || rate < 0.1 || rate > 16) return {status:'waiting'};
  return {status:'ready',time,duration,rate,readyState,paused:value.paused===true,ended:value.ended===true};
}
function createEmbeddedMediaBridge({getWindow,authorize,diagnostic=()=>{}}) {
  let lastReport='';
  const report=(reason,details={})=>{const key=JSON.stringify([reason,details]);if(key!==lastReport){lastReport=key;diagnostic('playback_state',{reason,...details});}};
  async function playback(event, options) {
    if (!authorize(event) || !options || !/^BV[0-9A-Za-z]{10}$/.test(options.bvid || '')
        || !Number.isSafeInteger(options.page) || options.page < 1 || options.page > 10000)
      { report('denied'); return {status:'denied'}; }
    const action=options.action || 'state';
    if (!['state','seek','play','pause','rate'].includes(action)) return {status:'denied'};
    if (action==='seek' && (!Number.isFinite(options.seconds) || options.seconds < 0 || options.seconds > 604800)) return {status:'denied'};
    if (action==='rate' && (!Number.isFinite(options.rate) || options.rate < 0.25 || options.rate > 4)) return {status:'denied'};
    const owner=getWindow()?.webContents;
    if (!owner || owner.isDestroyed()) return {status:'unavailable'};
    const frames=owner.mainFrame.framesInSubtree.filter(frame=>frame!==owner.mainFrame && matchingFrame(frame,options));
    if (frames.length!==1) { report('frame_count',{matching:frames.length,total:owner.mainFrame.framesInSubtree.length});return {status:'waiting'}; }
    const frame=frames[0];
    try {
      if (action!=='state') {
        // Commands are fixed operations with finite numeric arguments.
        const command=action==='seek' ? `media.currentTime=Math.min(${options.seconds},media.duration);`
          : action==='pause' ? 'media.pause();' : action==='play' ? 'await media.play();'
          : `media.playbackRate=${options.rate};`;
        await frame.executeJavaScript(`(async()=>{const media=[...document.querySelectorAll('video,bwp-video')].find(n=>Number.isFinite(Number(n.currentTime))&&Number(n.readyState)>=1);if(media){${command}}})()`);
      }
      const result=await frame.executeJavaScript(SNAPSHOT);
      if (!authorize(event) || getWindow()?.webContents!==owner || !matchingFrame(frame,options)) return {status:'denied'};
      const clean=cleanState(result);
      report(clean.status,clean.status==='ready'?{minute:Math.floor(clean.time/60),paused:clean.paused,rate:clean.rate}:{});
      return clean;
    } catch(error) { report('execution_error',{message:String(error.message).replace(/https?:\/\/\S+/g,'[url]').slice(0,180)});return {status:'waiting'}; }
  }
  return {playback};
}
module.exports={createEmbeddedMediaBridge,matchingFrame,cleanState,SNAPSHOT};
