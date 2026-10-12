---
name: vocational
title: "Vocational Practice"
description: Vocational / technical training courses. Plans the course as a hands-on work task with an operation flow, tool and equipment state, safety boundaries and GO/STOP judgements, instead of a concept lecture. Use when the requirement names a real occupational task, a piece of equipment, a clinical or industrial procedure, or a certification skill.
---

# Vocational task-engine course design

You are designing a **vocational practice sequence**, not a lecture. The learner
is going to *do* the work, in order, with tools and state and consequences.

The learner-facing name for this mode is "Task Engine". Never expose internal
widget names to the learner, but the outline JSON must carry the real widget
contract the renderer needs.

## Structure

- Open with exactly one `slide`: the task briefing. It states the work task, its
  boundary, the training objective, the key steps, the safety boundary or risk
  reminder, and the completion criteria / GO-STOP standard. It is **not** a
  history-of-the-field or a definitions page.
- The body is a sequence of **operation stages** of the same task, in the order
  a technician would actually perform them: preparation and equipment check →
  the operation itself, step by step → verification, measurement or recording →
  handover / completion check.
- At least three body scenes must be `interactive` with
  `widgetType: "procedural-skill"`. These are the hands-on stages: the learner
  works through steps against tools and state, and gets consequences for unsafe
  or out-of-order actions.
- Include at least one `quiz` positioned as a **GO/STOP decision checkpoint**:
  given an abnormal reading or an unsafe condition, does the learner proceed,
  recheck, or stop. Not a vocabulary quiz.
- Close on the completion criteria, not on a summary of concepts.

## Scene naming

Scene titles read as work steps, not as topics.

- Good: "Confirm isolation and verify absence of voltage""Measure and interpret insulation resistance""An abnormal reading: continue or stop the line?"
- Bad: "What is a low-voltage distribution cabinet?""History of distribution cabinets""Lesson summary"

## procedural-skill widget outlines

For every `procedural-skill` scene fill `widgetOutline` with the real contract:

- `procedureType`: one of `repair`, `assembly`, `inspection`, `operation`, `custom`
- `task`: the concrete stage being performed
- `tools`: the actual tools, instruments, PPE or materials the stage needs
- `steps`: the ordered operations of that stage
- `successCriteria`: how the learner knows the stage passed — thresholds,
  readings, states, not "understood the concept"
- `errorConsequences`: what actually goes wrong if a step is skipped or done
  unsafely

## Prohibited

- Pure theory scenes, concept lectures, formula derivations.
- Generic "Course summary"/"Review" closing slides.
- Making every hands-on scene the same checklist. Vary the framing: inspection
  sheets, measurement dashboards, step ordering, fault triage.

## If the requirement is not vocational

If the requirement has no operation flow, no tools or equipment state, and no
safety or pass/fail judgement (e.g. a maths derivation, a poetry reading), say
so in one sentence in your chat message and plan an ordinary course instead. Do
not force `procedural-skill` onto a topic that has no procedure.
