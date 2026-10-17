'use strict';
// Merge only adjacent pages of the same outline when all original body elements
// fit together. Narration/audio stays byte-for-byte intact and in its old order.
const baseTitle=title=>String(title).replace(/\s*\(continued\s+\d+\)$/i,'');
const baseOutline=id=>String(id).replace(/_page_\d+$/,'');
const safeAction=action=>['speech','spotlight'].includes(action.type)||(action.type==='laser'&&typeof action.elementId==='string'&&!['x','y','points','path'].some(key=>key in action));
const heading=elements=>elements.find(e=>e.type==='text'&&e.top<=130&&Array.from(String(e.content||'').matchAll(/font-size\s*:\s*([\d.]+)px/gi)).some(m=>+m[1]>=28));
function compactAdjacentSlides(scenes,layout){
  const output=[];
  for(const original of scenes){
    const previous=output.at(-1);
    let merged=null;
    if(previous?.type==='slide'&&original.type==='slide'&&previous.outlineId&&baseOutline(previous.outlineId)===baseOutline(original.outlineId)&&baseTitle(previous.title)===baseTitle(original.title)&&
       [...(previous.actions||[]),...(original.actions||[])].every(safeAction)){
      const left=previous.content.canvas,right=original.content.canvas;
      const a=heading(left.elements),b=heading(right.elements);
      if(a&&b&&JSON.stringify(left.background)===JSON.stringify(right.background)){
        const body=[...left.elements.filter(e=>e!==a),...right.elements.filter(e=>e!==b)];
        if(body.filter(e=>e.type==='image').length<=1&&body.every(e=>['text','image','latex'].includes(e.type)&&!e.groupId&&!e.rotate&&!e.vertical&&!e.clip)){
          const image=body.find(e=>e.type==='image');
          // Put the original figure beside the textual sequence, without changing
          // narration order. Only its position changes, not pixels or aspect ratio.
          const candidate={...left,elements:image?[a,image,...body.filter(e=>e!==image)]:[a,...body]};
          try{
            const pages=layout(candidate);
            if(pages.length===1){
              const ids=pages[0].elements.map(e=>e.id);
              if(new Set(ids).size===ids.length&&candidate.elements.every(e=>ids.includes(e.id))){
                const actions=[...(previous.actions||[]),...(original.actions||[]).map(action=>['spotlight','laser'].includes(action.type)&&action.elementId===b.id?{...action,elementId:a.id}:action)];
                if(actions.every(action=>!['spotlight','laser'].includes(action.type)||ids.includes(action.elementId))){
                  merged={...previous,content:{...previous.content,canvas:{...left,elements:pages[0].elements}},actions,
                    compactedFromSceneIds:[...(previous.compactedFromSceneIds||[previous.id]),...(original.compactedFromSceneIds||[original.id])]};
                }
              }
            }
          }catch{/* Preserve both original pages if safe layout is not established. */}
        }
      }
    }
    if(merged)output[output.length-1]=merged;else output.push(original);
  }
  const counts=new Map();
  return output.map((scene,index)=>{
    if(scene.type!=='slide'||!scene.outlineId)return {...scene,order:index+1};
    const key=baseOutline(scene.outlineId),number=(counts.get(key)||0)+1;counts.set(key,number);
    const title=baseTitle(scene.title)+(number>1?' (continued '+number+')':'');
    return {...scene,title,order:index+1};
  });
}
module.exports={compactAdjacentSlides};
