// DeepSteam: distinguish visible teaching, original questions, and feedback
// displayed only after quiz submission. This never records student mastery.
exports.markSourceQuestions = function(units, text) {
  for (let i=0;i<units.length;i++) {
    if (!/[?\uFF1F]$/.test(units[i].text)) continue;
    units[i].question=true;
    for(let j=i-1;j>=0;j--) {
      if (/[.!?\u3002\uFF01\uFF1F;\uFF1B]$/.test(units[j].text) ||
          /\n\s*\n/.test(text.slice(units[j].end,units[j+1].start))) break;
      units[j].question=true;
    }
  }
  let answer=false;
  for(let i=0;i<units.length;i++) {
    const unit=units[i];
    if(i && /\n\s*\n/.test(text.slice(units[i-1].end,unit.start))) answer=false;
    if(unit.question)answer=false;
    if(/^(?:Answer|Solution|\u7b54\u6848|\u89e3\u7b54|\u89e3\u6790)\s*[:\uFF1A]/i.test(unit.text))answer=true;
    unit.practiceAnswer=answer;
  }
  return units;
};

exports.extendDelivery = function(delivery, scenes, contract) {
  exports.markSourceQuestions(contract.units,contract.text);
  const blocks=[];
  for(const scene of scenes) {
    if(scene.content?.type!=='quiz')continue;
    for(const question of scene.content.questions) {
      // quiz-view's QuestionCard renders this field only when result exists.
      // Correct-answer fields, grading prompts, options and scripts stay excluded.
      if(typeof question.analysis!=='string'||!question.analysis.trim())continue;
      const text=question.analysis.replace(/<[^>]*>/g,' ').replace(/\s+/g,' ').trim();
      if(!text)continue;
      blocks.push(text);
      delivery.excerpts.push({id:'r_'+(delivery.excerpts.length+1),channel:'post_submission',text,
        sceneId:scene.id,questionId:question.id,availableAfter:'quiz_submission'});
    }
  }
  return {...delivery,postSubmission:blocks.join('\n\n')};
};

exports.auditChannelHints = function(contract) {
  return 'SOURCE_QUESTION_IDS='+JSON.stringify(contract.units.filter(u=>u.question).map(u=>u.id))+
    '\nPOST_SUBMISSION_SOURCE_IDS='+JSON.stringify(contract.units.filter(u=>u.practiceAnswer).map(u=>u.id))+
    '\nQuestion excerpts may cover ALL clauses of those original source questions, including comma-separated premises. '+
    'The post_submission channel contains quiz.analysis actually rendered in review after the learner submits. '+
    'It may cover ONLY the explicit source Answer/Solution units listed above, never replace the core teaching. '+
    'Record channel=post_submission with r_* evidenceIds for that deferred feedback. This is planned post-submission coverage, '+
    'not already-delivered teaching or student mastery. Correct-answer fields, grading/commentPrompt instructions and distractors still cannot count.';
};
