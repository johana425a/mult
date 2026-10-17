"use strict";
const {randomUUID} = require('node:crypto');
// DeepSteam: source-image retention is deterministic, not a second attempt to
// regenerate an otherwise complete lesson. These reference pages do not replace
// conceptual teaching and still undergo the unchanged source-fidelity audit.
exports.retainOriginalSourceImages = function retainOriginalSourceImages(scenes, images, stageId) {
  if (!images?.length) return scenes;
  const sourceById = new Map(images.map(image => [image.id, image.src]));
  scenes = scenes.map(scene => {
    if (scene.content?.type !== 'interactive' || typeof scene.content.html !== 'string') return scene;
    // Explicit img_N placeholders are source identities, not relative URLs.
    // Bind their unchanged pixels before iframe loading or a failed request
    // can disable an otherwise functional interaction.
    const html = scene.content.html.replace(/<img\b[^>]*>/gi, tag => tag.replace(
      /\bsrc\s*=\s*(?:"(img_\d+)"|'(img_\d+)'|(img_\d+)(?=[\s/>]))/gi,
      (_attribute, doubleQuoted, singleQuoted, unquoted) => {
        const id = doubleQuoted || singleQuoted || unquoted;
        const src = sourceById.get(id);
        if (typeof src !== 'string' || !/^data:image\/(?:png|jpeg|webp);base64,[A-Za-z0-9+/=]+$/.test(src))
          throw Error('SOURCE_REFERENCE_IMAGE: interactive source image is unavailable: ' + id);
        return 'src="' + src + '"';
      }));
    return html === scene.content.html ? scene : {...scene, content: {...scene.content, html}};
  });
  const shown = new Set();
  for (const scene of scenes) {
    if (scene.content?.type !== 'slide') continue;
    for (const element of scene.content.canvas?.elements || []) {
      if (element.type === 'image') shown.add(element.src);
    }
  }
  const missing = images.filter(image => !shown.has(image.src) && !shown.has(image.id));
  if (!missing.length) return scenes;
  const first = scenes.find(scene => scene.content?.type === 'slide');
  if (!first) throw Error('SOURCE_REFERENCE_LAYOUT: a slide canvas is required to retain original figures');
  const additions = missing.map((image, index) => {
    if (!image.src || !Number.isFinite(image.width) || !Number.isFinite(image.height) || image.width <= 0 || image.height <= 0)
      throw Error('SOURCE_REFERENCE_LAYOUT: original figure dimensions are missing; no image was discarded');
    const title = image.pageNumber > 0 ? `Source reference: PDF page ${image.pageNumber}` : `Source reference: ${image.id}`;
    const scale = Math.min(900 / image.width, 300 / image.height);
    const width = image.width * scale, height = image.height * scale;
    const id = 'source-reference-' + randomUUID();
    return {
      id, stageId, type:'slide', title, order:scenes.length+index+1,
      outlineId:'retained-source-' + image.id, createdAt:Date.now(), updatedAt:Date.now(),
      actions:[{id:'action-'+randomUUID(),type:'speech',text:
        image.pageNumber > 0 ? `Original source reference, physical PDF page ${image.pageNumber}. This unaltered page is retained for comparison with the teaching material.` :
        'This unaltered original source image is retained for comparison with the teaching material.'}],
      content:{type:'slide',canvas:{...first.content.canvas,id:'canvas-'+randomUUID(),viewportSize:1000,viewportRatio:0.5625,
        background:{type:'solid',color:'#ffffff'},elements:[
          {id:id+'-title',type:'text',left:50,top:50,width:900,height:76,rotate:0,
            content:`<p style="font-size:32px"><strong>${title}</strong></p>`,defaultFontName:'',defaultColor:'#183247'},
          {id:id+'-image',type:'image',left:(1000-width)/2,top:140,width,height,src:image.src,rotate:0,fixedRatio:true},
          {id:id+'-notice',type:'text',left:50,top:454,width:900,height:58,rotate:0,
            content:'<p style="font-size:24px">Original source image; retained without cropping or changes.</p>',defaultFontName:'',defaultColor:'#526777'},
        ]}},
    };
  });
  return [...scenes, ...additions];
};
