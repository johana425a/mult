'use strict';
// Follow within a stable scrollport. Never resize the list from its current
// screen position: outer scrolling + flex layout + scroll anchoring forms a
// feedback loop and makes the entire player jump on successive frames.
function visibleListViewport(list) {
  const win=list.ownerDocument.defaultView,rect=list.getBoundingClientRect();
  let top=Math.max(rect.top+list.clientTop,0),bottom=Math.min(rect.top+list.clientTop+list.clientHeight,win.innerHeight);
  for(let parent=list.parentElement;parent;parent=parent.parentElement){
    if(!/(auto|scroll|hidden|clip)/.test(win.getComputedStyle(parent).overflowY))continue;
    const bounds=parent.getBoundingClientRect();
    top=Math.max(top,bounds.top+parent.clientTop);
    bottom=Math.min(bottom,bounds.top+parent.clientTop+parent.clientHeight);
  }
  return {offset:Math.max(0,top-rect.top-list.clientTop),height:Math.max(0,bottom-top)};
}
function followTranscriptRow(list) {
  if(!list)return false;
  const row=list.querySelector('[data-active-cue="true"]');if(!row)return false;
  const viewport=visibleListViewport(list);if(viewport.height<16)return false;
  const listTop=list.getBoundingClientRect().top+list.clientTop;
  const rowTop=row.getBoundingClientRect().top-listTop+list.scrollTop;
  const center=rowTop+row.clientHeight/2-viewport.offset-viewport.height/2;
  const band=Math.max(0,(viewport.height-row.clientHeight)/4);
  const target=Math.min(Math.max(0,Math.min(Math.max(list.scrollTop,center-band),center+band)),Math.max(0,list.scrollHeight-list.clientHeight));
  if(Math.abs(list.scrollTop-target)<1)return false;
  list.scrollTo({top:target,behavior:'instant'});return true;
}
function observeTranscriptFollow(list) {
  if(!list)return ()=>{};
  const win=list.ownerDocument.defaultView;let frame=0,disposed=false;
  // Identical at every scroll offset; resizing a window is handled by CSS.
  const previous={maxHeight:list.style.maxHeight,minHeight:list.style.minHeight,overflowAnchor:list.style.overflowAnchor};
  list.style.maxHeight='min(48vh, 460px)';list.style.minHeight='0px';list.style.overflowAnchor='none';
  const update=event=>{
    if(disposed||event?.target===list)return;
    win.cancelAnimationFrame(frame);frame=win.requestAnimationFrame(()=>followTranscriptRow(list));
  };
  const resize=typeof win.ResizeObserver==='function'?new win.ResizeObserver(update):null;resize?.observe(list);
  const mutation=typeof win.MutationObserver==='function'?new win.MutationObserver(update):null;
  mutation?.observe(list,{subtree:true,attributes:true,attributeFilter:['data-active-cue']});
  win.addEventListener('resize',update);win.addEventListener('scroll',update,true);update();
  return ()=>{disposed=true;win.cancelAnimationFrame(frame);resize?.disconnect();mutation?.disconnect();win.removeEventListener('resize',update);win.removeEventListener('scroll',update,true);Object.assign(list.style,previous);};
}
module.exports={visibleListViewport,followTranscriptRow,observeTranscriptFollow};
