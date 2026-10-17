'use strict';
const fs=require('node:fs/promises'),path=require('node:path'),crypto=require('node:crypto');
const sharp=require('sharp');
// Some models return declarative question.media instead of Markdown. Convert
// only explicit supplied-image references before the common renderer; never
// silently lose a figure that the question asks the learner to inspect.
function normalizeStructuredQuestionImages(original){
  const question={...original};
  if(question.media===undefined)return question;
  if(!Array.isArray(question.media))throw Error('Quiz media must be an array of supplied source images');
  for(const media of question.media){
    if(!media||media.type!=='image'||typeof media.assetId!=='string'||!/^img_[1-9]\d*$/.test(media.assetId))
      throw Error('Quiz media must reference a supplied source image');
    let reference=media.assetId;
    if(media.crop!==undefined&&media.crop!==null){
      const crop=media.crop,coordinates=[crop.x,crop.y,crop.width,crop.height];
      if(crop.unit!=='px'||!coordinates.every(Number.isSafeInteger)||crop.x<0||crop.y<0||crop.width<1||crop.height<1)
        throw Error('Invalid quiz source image crop');
      reference+='#xywh=pixel:'+coordinates.join(',');
    }
    const alt=String(media.alt||'Original source figure').replace(/[\[\]\\\r\n]/g,' ').trim();
    if(typeof question.question!=='string')throw Error('Quiz question text is missing');
    if(!question.question.includes(']('+reference+')'))question.question+='\n\n!['+alt+']('+reference+')';
    // Captions, answer keys and sourceReferences are not automatically exposed
    // before submission: a caption may contain the answer to a figure question.
  }
  delete question.media;
  return question;
}
async function resolveQuizSourceImages(content,imageMapping,stageId,classroomsDir){
  if(!Array.isArray(content?.questions))return content;
  if(!/^[A-Za-z0-9_-]+$/.test(stageId))throw Error('Invalid classroom asset identity');
  const root=path.resolve(classroomsDir),folder=path.resolve(root,stageId,'media');
  if(!folder.startsWith(root+path.sep))throw Error('Invalid classroom asset boundary');
  const expression=/!\[([^\]]*)\]\((img_\d+)(?:#xywh=pixel:(\d+),(\d+),(\d+),(\d+))?\)/gi;
  const questions=[];
  for(const original of content.questions){
    const question=normalizeStructuredQuestionImages(original),references=[...(original.sourceImageReferences||[])];
    for(const field of ['question','analysis']){
      const value=question[field];if(typeof value!=='string')continue;
      let updated='',cursor=0;
      for(const match of value.matchAll(expression)){
        const [whole,alt,id,...coordinates]=match,src=imageMapping[id];
        if(typeof src!=='string'||!/^data:image\/(png|jpeg|webp);base64,/.test(src))throw Error('Quiz source image is unavailable: '+id);
        const buffer=Buffer.from(src.slice(src.indexOf(',')+1),'base64'),sourceHash=crypto.createHash('sha256').update(buffer).digest('hex');
        const crop=coordinates[0]===undefined?null:{left:+coordinates[0],top:+coordinates[1],width:+coordinates[2],height:+coordinates[3]};
        let pipeline=sharp(buffer);
        if(crop){
          const metadata=await pipeline.metadata();
          if(crop.width<1||crop.height<1||crop.left+crop.width>metadata.width||crop.top+crop.height>metadata.height)throw Error('Quiz figure region is outside the supplied source image');
          pipeline=pipeline.extract(crop);
        }
        const filename='quiz-source-'+crypto.createHash('sha256').update(sourceHash+JSON.stringify(crop)).digest('hex').slice(0,20)+'.png';
        await fs.mkdir(folder,{recursive:true});
        const rendered=await pipeline.png().toBuffer();
        try{await fs.writeFile(path.join(folder,filename),rendered,{flag:'wx'});}catch(error){if(error.code!=='EEXIST')throw error;}
        const uri='/api/classroom-media/'+stageId+'/media/'+filename;
        updated+=value.slice(cursor,match.index)+'!['+alt+']('+uri+')';cursor=match.index+whole.length;
        references.push({field,sourceImageId:id,sourceSha256:sourceHash,region:crop,url:uri,originalSourceRetained:true});
      }
      question[field]=updated+value.slice(cursor);
      if(/!\[[^\]]*\]\(img_\d+/i.test(question[field]))throw Error('Unresolved quiz source image reference');
    }
    if(references.length)question.sourceImageReferences=references;
    questions.push(question);
  }
  return {...content,questions};
}
module.exports={resolveQuizSourceImages,normalizeStructuredQuestionImages};
