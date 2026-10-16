'use strict';
// DeepSteam 2026-10-16: render official pages in an isolated native view.
// No media proxy, account export, iframe policy override or synthetic captions.
const RULES=[
 ['bilibili',['www.bilibili.com','bilibili.com'],/^\/video\/(BV[0-9A-Za-z]{10})\/?$/,'bilibili.com'],
 ['youku',['v.youku.com'],/^\/v_show\/id_([A-Za-z0-9=]+)(?:\.html)?\/?$/,'youku.com'],
 ['iqiyi',['www.iqiyi.com','iqiyi.com','m.iqiyi.com'],/^\/v_([A-Za-z0-9]+)\.html\/?$/,'iqiyi.com'],
 ['douyin',['www.douyin.com','douyin.com'],/^\/video\/(\d{10,})\/?$/,'douyin.com'],
 ['xigua',['www.ixigua.com','ixigua.com','m.ixigua.com'],/^\/(?:video\/)?(\d{10,})\/?$/,'ixigua.com'],
 ['kuaishou',['www.kuaishou.com','kuaishou.com'],/^\/short-video\/([A-Za-z0-9]+)\/?$/,'kuaishou.com'],
];
function source(value){try{const u=new URL(value);if(!['https:','http:'].includes(u.protocol)||u.username||u.password||(u.port&&!['80','443'].includes(u.port)))return null;
 const host=u.hostname.toLowerCase().replace(/\.$/,''),p=decodeURIComponent(u.pathname);
 for(const [platform,hosts,pattern,domain]of RULES){const m=hosts.includes(host)&&pattern.exec(p);if(!m)continue;
 const page=platform==='bilibili'?Number(u.searchParams.get('p')||1):1;if(!Number.isSafeInteger(page)||page<1||page>10000)return null;
 const canonical=platform==='bilibili'?`https://www.bilibili.com/video/${m[1]}/?p=${page}`:platform==='youku'?`https://v.youku.com/v_show/id_${m[1]}.html`:platform==='iqiyi'?`https://www.iqiyi.com/v_${m[1]}.html`:platform==='douyin'?`https://www.douyin.com/video/${m[1]}`:platform==='xigua'?`https://www.ixigua.com/${m[1]}`:`https://www.kuaishou.com/short-video/${m[1]}`;
 return {platform,id:platform==='bilibili'?m[1]+'@'+page:m[1],url:canonical,domain};}return null;}catch{return null}}
function sameSource(a,b){const x=source(a),y=source(b);return !!x&&!!y&&x.platform===y.platform&&x.id===y.id;}
function allowedNavigation(value,s){try{const u=new URL(value);return u.protocol==='https:'&&!u.username&&!u.password&&!u.port&&(u.hostname===s.domain||u.hostname.endsWith('.'+s.domain));}catch{return false}}
function inspectPage(captions=false){
 if(['www.ixigua.com','m.ixigua.com','ixigua.com'].includes(globalThis.location?.hostname)){
  const prompt=document.querySelector('.primary-modal'),cancel=prompt?.querySelector('.primary-modal__cancel');
  if(prompt?.textContent.replace(/\s/g,'')==='打开App看完整内容否是'&&cancel?.textContent.trim()==='否'&&cancel.getBoundingClientRect().width>0)cancel.click();
  const download=document.querySelector('#modal-root .modal-overlay');
  if(download?.textContent.replace(/\s/g,'')==='打开抖音扫码下载西瓜视频'&&download.getBoundingClientRect().width>0)download.click();
 }
 const all=Array.from(document.querySelectorAll('video,bwp-video')).filter(v=>typeof v.play==='function');
 const media=all.filter(v=>Number.isFinite(v.duration)&&v.duration>0&&v.readyState>=1).sort((a,b)=>{const x=a.getBoundingClientRect(),y=b.getBoundingClientRect();return y.width*y.height-x.width*x.height;})[0];
 const text=(document.body?.innerText||'').slice(0,12000);
 let status=media?'ready':'loading';
 // Some sites preload the main video behind a separate advertising surface.
 // An advancing element alone is not sufficient evidence of main-content play.
 if(media){const r=media.getBoundingClientRect();const ad=Array.from(document.querySelectorAll('span,div,p,label')).some(n=>{
  if(n.children.length>1||n.textContent.trim()!=='广告')return false;const b=n.getBoundingClientRect(),s=getComputedStyle(n);
  return s.visibility!=='hidden'&&s.display!=='none'&&b.width>0&&b.height>0&&b.left>=r.left-2&&b.right<=r.right+2&&b.top>=r.top-2&&b.bottom<=r.bottom+2;
 });if(ad)status='advertisement';}
 if(!media){if(/因版权原因无法观看|所在地区|地区.{0,8}无法播放|not available in your (country|region)/i.test(text))status='region_restricted';
 else if(/内容可能已删除|视频已删除|视频不存在|视频已下架/.test(text))status='removed';
 else if(/请完成.{0,10}验证|拖动.{0,15}滑块|安全验证/.test(text))status='verification_required';
 else if(/登录后.{0,8}(观看|播放)|请登录后.{0,8}(观看|播放)/.test(text))status='login_required';
 else if(!all.length&&Array.from(document.querySelectorAll('button,a,span,div')).some(n=>n.children.length<2&&n.textContent.trim()==='立即播放'&&n.getBoundingClientRect().width>0))status='awaiting_play';
 else if(/打开App看完整内容|下载西瓜视频查看/.test(text)&&!all.length)status='app_required';
 else if(/^\s*\{\s*"result"\s*:\s*2\s*,/.test(text))status='platform_rejected';}
 const result={status,title:document.title.slice(0,1000),time:media?.currentTime||0,duration:media?.duration||0,rate:media?.playbackRate||1,paused:media?.paused??true,ended:media?.ended??false};
 if(captions&&media&&status==='ready'){
  const tracks=Array.from(media.textTracks||[]).filter(t=>['subtitles','captions'].includes(t.kind));
  const track=tracks.find(t=>/^zh/i.test(t.language))||tracks[0];
  if(track){if(track.mode==='disabled')track.mode='hidden';const cues=Array.from(track.cues||[]);if(cues.length>20000)return {...result,captionStatus:'too_large'};
   let bytes=0;result.cues=[];for(const c of cues){const value=String(c.text||'');bytes+=new TextEncoder().encode(value).length;if(bytes>2097152)return {...result,cues:[],captionStatus:'too_large'};result.cues.push({from:c.startTime,to:c.endTime,content:value});}
   result.language=track.language||'';result.captionStatus=result.cues.length?'available':'pending';
  }else result.captionStatus='no_track';
 }
 return result;
}
function cleanState(value){
 const statuses=['ready','loading','awaiting_play','advertisement','region_restricted','removed','verification_required','login_required','app_required','platform_rejected'];
 if(!value||!statuses.includes(value.status))return {status:'loading'};
 const out={status:value.status,title:typeof value.title==='string'?value.title.slice(0,1000):''};
 if(value.status==='ready'){
  if(![value.time,value.duration,value.rate].every(Number.isFinite)||value.time<0||value.duration<=0||value.duration>604800||value.time>value.duration+2||value.rate<.1||value.rate>16)return {status:'loading'};
  Object.assign(out,{time:value.time,duration:value.duration,rate:value.rate,paused:value.paused===true,ended:value.ended===true});
 }return out;
}
function validateCues(cues){if(!Array.isArray(cues)||!cues.length||cues.length>20000)return false;let bytes=0;return cues.every(c=>c&&Number.isFinite(c.from)&&Number.isFinite(c.to)&&c.from>=0&&c.to>=c.from&&c.to<=604800&&typeof c.content==='string'&&(bytes+=Buffer.byteLength(c.content))<=2097152);}
function createDomesticMediaBridge({WebContentsView,getWindow,authorize,serviceRequest,getBilibiliSession}){
 let active=null;
 function close(){const a=active;if(!a)return;active=null;clearTimeout(a.expiry);a.owner.webContents.removeListener('did-start-navigation',a.navigation);a.owner.removeListener('closed',close);try{a.owner.contentView.removeChildView(a.view);}catch{}if(!a.view.webContents.isDestroyed())a.view.webContents.close();}
 function alive(event,o){return authorize(event)&&active&&active.owner===getWindow()&&active.instance===o.instance&&sameSource(active.source.url,o.url)&&!active.view.webContents.isDestroyed();}
 function layout(a,b){if(!b||![b.x,b.y,b.width,b.height].every(Number.isFinite))return false;const [w,h]=a.owner.getContentSize(),z=a.owner.webContents.getZoomFactor();const r={x:Math.round(b.x*z),y:Math.round(b.y*z),width:Math.round(b.width*z),height:Math.round(b.height*z)};
  const visible=b.visible===true&&r.width>=100&&r.height>=100&&r.x>=0&&r.y>=0&&r.x+r.width<=w+1&&r.y+r.height<=h+1;
  if(visible)a.view.setBounds(r);a.view.setVisible(visible);clearTimeout(a.expiry);a.expiry=setTimeout(()=>{if(active===a)a.view.setVisible(false)},2500);return true;
 }
 async function handle(event,o={}){
  if(!authorize(event)||!o||typeof o.instance!=='string'||!/^[a-zA-Z0-9_-]{8,80}$/.test(o.instance))return {status:'denied'};
  if(o.action==='mount'){
   const s=source(o.url),owner=getWindow();if(!s||!owner||owner.isDestroyed())return {status:'denied'};
   if(active&&active.instance===o.instance&&sameSource(active.source.url,o.url)){layout(active,o.bounds);return {status:'mounted'};}
   close();const view=new WebContentsView({webPreferences:{...(s.platform==='bilibili'&&getBilibiliSession?{session:getBilibiliSession()}:{partition:'persist:deepsteam-domestic-'+s.platform}),sandbox:true,contextIsolation:true,nodeIntegration:false,webSecurity:true,allowRunningInsecureContent:false,backgroundThrottling:false,offscreen:owner.webContents.isOffscreen?.()===true}});
   const a={owner,source:s,view,instance:o.instance,started:Date.now(),loadError:false};active=a;
   if(s.platform!=='bilibili'){view.webContents.session.setPermissionRequestHandler((_w,_p,cb)=>cb(false));view.webContents.session.setPermissionCheckHandler(()=>false);}
   view.webContents.setWindowOpenHandler(()=>({action:'deny'}));
   view.webContents.on('will-navigate',(e,url)=>{if(!allowedNavigation(url,s))e.preventDefault()});
   view.webContents.on('will-redirect',(e,url)=>{if(!allowedNavigation(url,s))e.preventDefault()});
   view.webContents.on('did-fail-load',(_e,code,_d,_u,main)=>{if(main&&code!==-3)a.loadError=true});
   if(s.platform==='bilibili')view.webContents.on('dom-ready',()=>{
    // Keep the official player and its account-aware quality menu inside the
    // allocated view. This changes layout only; it does not alter entitlement.
    void view.webContents.insertCSS('html,body{margin:0!important;overflow:hidden!important;background:#000!important}.bili-header{display:none!important}#bilibili-player{position:fixed!important;inset:0!important;width:100vw!important;height:100vh!important;min-width:0!important;z-index:100000!important}.bpx-player-sending-area{display:none!important}').catch(()=>{});
   });
   if(s.platform==='xigua')view.webContents.on('dom-ready',()=>{
    void view.webContents.insertCSS('html,body{overflow:hidden!important}.xigua-detailvideo-video{position:fixed!important;inset:0!important;width:100vw!important;height:100vh!important;max-width:none!important;z-index:100!important}.xigua-detailvideo-video .xgplayer{width:100%!important;height:100%!important}').catch(()=>{});
   });
   a.navigation=(_e,_url,inPlace,isMain)=>{if(isMain&&!inPlace)close()};
   owner.webContents.on('did-start-navigation',a.navigation);owner.once('closed',close);
   owner.contentView.addChildView(view);if(view.webContents.isOffscreen?.())view.webContents.setFrameRate(20);view.webContents.setZoomFactor(.75);layout(a,o.bounds);
   void view.webContents.loadURL(s.url).catch(()=>{a.loadError=true});return {status:'mounted'};
  }
  if(!alive(event,o))return {status:'closed'};
  const a=active,wc=a.view.webContents;
  if(o.action==='unmount'){close();return {status:'closed'}}
  if(o.action==='bounds'){layout(a,o.bounds);return {status:'mounted'}}
  if(!['state','captions','play','pause','seek','rate'].includes(o.action))return {status:'denied'};
  if(!sameSource(wc.getURL(),a.source.url))return {status:a.loadError?'network_error':'loading'};
  if(a.loadError)return {status:'network_error'};
  try{
   const run=script=>new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(new Error('PLAYER_TIMEOUT')),6000);wc.executeJavaScript(script).then(v=>{clearTimeout(timer);resolve(v)},e=>{clearTimeout(timer);reject(e)})});
   const before=await run(`(${inspectPage.toString()})(false)`);
   if(before.status==='advertisement')return {status:'advertisement',captionStatus:'pending'};
   if(['play','pause','seek','rate'].includes(o.action)){
    if(o.action==='seek'&&(!Number.isFinite(o.seconds)||o.seconds<0||o.seconds>604800))return {status:'denied'};
    if(o.action==='rate'&&(!Number.isFinite(o.rate)||o.rate<.25||o.rate>4))return {status:'denied'};
    const command=o.action==='play'?'v.play().catch(()=>{});':o.action==='pause'?'v.pause();':o.action==='seek'?`v.currentTime=Math.min(${o.seconds},v.duration);`:`v.playbackRate=${o.rate};`;
    const activate=o.action==='play'?`else{const button=[...document.querySelectorAll('button,a,span,div')].find(n=>n.children.length<2&&n.textContent.trim()==='立即播放'&&n.getBoundingClientRect().width>0);button?.click();}`:'';
    await run(`{const v=[...document.querySelectorAll('video,bwp-video')].filter(v=>typeof v.play==='function'&&v.readyState>=1&&Number.isFinite(v.duration)).sort((a,b)=>b.clientWidth*b.clientHeight-a.clientWidth*a.clientHeight)[0];if(v){${command}}${activate}}`);
   }
   const value=o.action==='state'?before:await run(`(${inspectPage.toString()})(${o.action==='captions'})`);
   if(!alive(event,o)||!sameSource(wc.getURL(),a.source.url))return {status:'closed'};
   const clean=cleanState(value);if(clean.status==='loading'&&Date.now()-a.started>45000)clean.status='load_timeout';
   if(o.action!=='captions')return clean;
   if(!validateCues(value.cues))return {...clean,captionStatus:value.captionStatus||'no_track'};
   if(!/^[a-zA-Z0-9_-]{8,80}$/.test(o.materialId||'')||!/^ws_[a-zA-Z0-9]+$/.test(o.workspaceId||''))return {status:'denied'};
   const result=await serviceRequest(`/api/contest/internal/domestic-captions/${o.materialId}?dt_workspace=${encodeURIComponent(o.workspaceId)}`,{method:'POST',body:{source_url:a.source.url,cues:value.cues,language:value.language,title:clean.title,duration_seconds:clean.duration}});
   return {status:'ready',captionStatus:'imported',segments:result.segments};
  }catch{return {status:'request_failed'}}
 }
 return {handle,close};
}
module.exports={source,sameSource,allowedNavigation,inspectPage,cleanState,validateCues,createDomesticMediaBridge};
