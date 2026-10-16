'use strict';
// Applied only inside the already-authorized official Bilibili embed frame.
// Keep account prompts, player controls, title and platform attribution intact.
function installPresentation() {
  const id='deepsteam-bilibili-presentation-v1';
  if(!document.getElementById(id)){
    const style=document.createElement('style');style.id=id;
    style.textContent='.bpx-player-relation-wrap[data-deepsteam-promo="hidden"]{display:none!important;pointer-events:none!important}';
    (document.head||document.documentElement).appendChild(style);
  }
  const apply=()=>{
    for(const wrap of document.querySelectorAll('.bpx-player-relation-wrap')){
      const text=wrap.querySelector('.bpx-player-relation-button')?.textContent?.replace(/\s+/g,'').trim()||'';
      if(/^进入哔哩哔哩[，,]?观看更高清/.test(text))wrap.setAttribute('data-deepsteam-promo','hidden');
    }
  };
  const key=Symbol.for('deepsteam.bilibili.presentation.v1');
  if(!window[key]){
    const observer=new MutationObserver(apply);
    observer.observe(document.documentElement,{childList:true,subtree:true,characterData:true});
    window[key]=observer;
  }
  apply();
}
const PRESENTATION='('+installPresentation.toString()+')();';
module.exports={installPresentation,PRESENTATION};
