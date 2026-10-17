'use strict';
/** Keep an already readable model-authored page instead of flattening every
 * image and text box into a separate full-width row. Unsafe/complex layouts
 * continue through the existing lossless paginator. No content is deleted. */
function retainAuthoredPage(content, size, bounds, layout) {
  if (!Array.isArray(content?.elements) || !content.elements.length) return null;
  if (content.continuationSlides?.length) return null;
  const {width,height,margin}=layout;
  const elements=[];
  for (const original of content.elements) {
    if (!['text','image'].includes(original.type) || original.groupId || original.rotate || original.vertical || original.clip) return null;
    if (![original.left,original.top,original.width,original.height].every(Number.isFinite)) return null;
    if (original.width<=0 || original.height<=0 || original.left<margin || original.top<margin || original.left+original.width>width-margin) return null;
    let element;
    try {element=size(structuredClone(original),original.width,height-margin-original.top);} catch {return null;}
    if (original.type==='image' && element.width<Math.min(320,original.width)-0.01) return null;
    element={...element,left:original.left,top:original.top};
    const box=bounds(element);
    if (box.left<margin || box.top<margin || box.right>width-margin+0.01 || box.bottom>height-margin+0.01) return null;
    for (const previous of elements) {
      const other=bounds(previous);
      if (box.left<other.right+8 && other.left<box.right+8 && box.top<other.bottom+8 && other.top<box.bottom+8) return null;
    }
    elements.push(element);
  }
  return [{...content,elements,continuationSlides:undefined}];
}

/** A single figure may share its vertical space with the following explanation.
 * Keep source order and all content, measuring with the existing font/image rules.
 * Complex diagrams and multiple-image arrangements still use the upstream flow. */
function flowBesideFigure(content,size,bounds,layout){
  const originals=content?.elements;
  if(!Array.isArray(originals)||originals.filter(e=>e.type==='image').length!==1||content.continuationSlides?.length)return null;
  if(originals.some(e=>!['text','image','latex'].includes(e.type)||e.groupId||e.rotate||e.vertical||e.clip))return null;
  const {width,height,margin,gap}=layout, usable=width-2*margin, bottom=height-margin;
  const title=originals[0];
  if(title.type!=='text'||title.top>130||!Array.from(String(title.content||'').matchAll(/font-size\s*:\s*([\d.]+)px/gi)).some(m=>+m[1]>=28))return null;
  const pages=[];let page,y,paired=false;
  const checked=(element)=>{
    const box=bounds(element);
    if(![box.left,box.top,box.right,box.bottom].every(Number.isFinite)||box.left<margin-.01||box.top<margin-.01||box.right>width-margin+.01||box.bottom>bottom+.01)throw Error('Unsafe compact bounds');
    for(const prior of page.elements){const b=bounds(prior);if(box.left<b.right+8&&b.left<box.right+8&&box.top<b.bottom+8&&b.top<box.bottom+8)throw Error('Unsafe compact overlap');}
    page.elements.push(element);
  };
  const next=()=>{
    page={...content,elements:[],continuationSlides:undefined};pages.push(page);
    const heading=size(structuredClone(title),usable,bottom-margin);
    heading.left=margin;heading.top=margin;
    if(pages.length>1)heading.id=title.id+'__compact_continuation_'+pages.length;
    checked(heading);y=heading.top+heading.height+gap;
    if(bottom-y<160)throw Error('Title too large for a compact layout');
  };
  try{
    next();
    for(let i=1;i<originals.length;i++){
      const original=originals[i];
      if(original.type==='image'){
        // Start a fresh body row, so text above never forces a smaller source image.
        if(page.elements.length>1)next();
        const image=size(structuredClone(original),Math.min(430,usable/2),bottom-y);
        image.left=margin;image.top=y;
        const rightLeft=margin+image.width+24,rightWidth=width-margin-rightLeft;
        if(rightWidth<320)throw Error('No readable explanation column');
        checked(image);
        let sideY=y,consumed=0;
        while(i+1<originals.length&&originals[i+1].type!=='image'){
          const item=size(structuredClone(originals[i+1]),rightWidth,bottom-sideY);
          if(item.height>bottom-sideY+.01)break;
          item.left=rightLeft;item.top=sideY;checked(item);
          sideY+=item.height+gap;i++;consumed++;
        }
        if(consumed)paired=true;
        y=Math.max(image.top+image.height+gap,sideY);
      }else{
        let item=size(structuredClone(original),usable,bottom-y);
        if(item.height>bottom-y+.01){next();item=size(structuredClone(original),usable,bottom-y);}
        item.left=margin;item.top=y;checked(item);y+=item.height+gap;
      }
    }
    return paired?pages:null;
  }catch{return null;}
}
function retainCompactTextPage(content,size,bounds,layout){
  const originals=content?.elements;
  if(!Array.isArray(originals)||!originals.length||content.continuationSlides?.length||originals.some(e=>!['text','latex'].includes(e.type)||e.groupId||e.rotate||e.vertical))return null;
  const {width,height,margin}=layout,elements=[];let top=margin;
  try{
    for(const original of originals){
      const element=size(structuredClone(original),width-2*margin,height-margin-top);
      element.left=margin;element.top=top;
      const box=bounds(element);
      if(![box.left,box.top,box.right,box.bottom].every(Number.isFinite)||box.left<margin||box.top<margin||box.right>width-margin+.01||box.bottom>height-margin+.01)return null;
      if(elements.length&&box.top<bounds(elements.at(-1)).bottom+8-.01)return null;
      elements.push(element);top=box.bottom+8;
    }
    return [{...content,elements,continuationSlides:undefined}];
  }catch{return null;}
}
function retainReadablePage(content,size,bounds,layout){
  return retainAuthoredPage(content,size,bounds,layout)||retainCompactTextPage(content,size,bounds,layout)||flowBesideFigure(content,size,bounds,layout);
}
module.exports={retainReadablePage,retainAuthoredPage,retainCompactTextPage,flowBesideFigure};
