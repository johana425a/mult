'use strict';
// Explicit opt-in diagnostic for the installed, owned Bilibili session. No
// credentials, identity, remote headers or URLs with account tokens are saved.
exports.run=async({BrowserWindow,WebContentsView,session,output})=>{
 const fs=require('node:fs'),{createDomesticMediaBridge}=require('./domestic-media.cjs'),sleep=ms=>new Promise(r=>setTimeout(r,ms));
 const result={hidden:true,desktopInput:false,installed:true,account:'owned desktop session',samples:[]};
 const save=()=>fs.writeFileSync(output,JSON.stringify(result,null,2));let owner,bridge,heartbeat;
 try{
  const nav=await(await session.defaultSession.fetch('https://api.bilibili.com/x/web-interface/nav',{signal:AbortSignal.timeout(12000)})).json();result.signedIn=nav.code===0&&nav.data?.isLogin===true;save();
  owner=new BrowserWindow({show:false,width:1320,height:900,webPreferences:{offscreen:true,sandbox:true,contextIsolation:true,nodeIntegration:false,backgroundThrottling:false}});await owner.loadURL('about:blank');
  bridge=createDomesticMediaBridge({WebContentsView,getWindow:()=>owner,authorize:e=>e.sender===owner.webContents,getBilibiliSession:()=>session.defaultSession,serviceRequest:async()=>{throw Error('No caption writes in quality diagnostic')}});
  const event={sender:owner.webContents},o={url:'https://www.bilibili.com/video/BV1SmpD6QEuX/',instance:'quality_acceptance'},bounds={x:0,y:0,width:1200,height:750,visible:true};
  const call=(action,extra={})=>bridge.handle(event,{...o,action,...extra});await call('mount',{bounds});const view=owner.contentView.children.find(v=>v.webContents&&v.webContents!==owner.webContents);view.webContents.setAudioMuted(true);heartbeat=setInterval(()=>void call('bounds',{bounds}),500);
  const state=`(()=>{const v=document.querySelector('video,bwp-video');return {time:v?.currentTime,duration:v?.duration,width:v?.videoWidth,height:v?.videoHeight,quality:document.querySelector('.bpx-player-ctrl-quality-result-name')?.textContent,menu:[...document.querySelectorAll('.bpx-player-ctrl-quality-menu-item')].map(n=>({value:n.getAttribute('data-value'),text:n.textContent.trim(),selected:n.classList.contains('bpx-state-active'),requiresLogin:!!n.querySelector('.bpx-player-ctrl-quality-badge-needlogin'),requiresVip:!!n.querySelector('.bpx-player-ctrl-quality-badge-bigvip')}))}})()`;
  const started=Date.now();let s;
  while(Date.now()-started<50000){s=await call('state');if(s.status==='ready')break;await sleep(700)}
  await sleep(4000);result.initial=await view.webContents.executeJavaScript(state);await call('rate',{rate:1});await call('pause');save();
  for(const [value,height,seek] of [['16',360,100],['64',720,250],['80',1080,400]]){
   const offered=result.initial.menu?.find(q=>q.value===value);if(!offered)continue;
   if((offered.requiresLogin&&!result.signedIn)||offered.requiresVip){result.samples.push({value,status:offered.requiresVip?'subscription_required':'login_required'});continue;}
   await view.webContents.executeJavaScript(`document.querySelector('.bpx-player-ctrl-quality-menu-item[data-value="${value}"]')?.click()`,true);
   // Seeking outside the existing buffered range confirms the newly selected
   // representation rather than measuring old frames left in the buffer.
   await sleep(1500);await call('seek',{seconds:seek});await call('play');
   const limit=Date.now()+24000;let a;
   do{await sleep(1000);a=await view.webContents.executeJavaScript(state)}while(Date.now()<limit&&a.height!==height);
   await call('play');await sleep(2500);const b=await view.webContents.executeJavaScript(state);
   result.samples.push({value,before:a,after:b,stayedInApp:view.webContents.getURL().startsWith('https://www.bilibili.com/video/BV1SmpD6QEuX/'),actualPlayback:b.time>a.time+1,resolutionVerified:b.height===height});save();
  }
  fs.writeFileSync(output.replace(/\.json$/,'.png'),(await view.webContents.capturePage()).toPNG());
  result.hidden=!owner.isVisible();result.finished=new Date().toISOString();
 }catch(e){result.error=String(e.message).replace(/https?:\/\/\S+/g,'[url]').slice(0,200)}
 finally{clearInterval(heartbeat);bridge?.close();owner?.destroy();save()}
};
