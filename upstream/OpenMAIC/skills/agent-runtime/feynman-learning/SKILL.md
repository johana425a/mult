---
name: feynman-learning
title: "Feynman Learning"
description: "Turn any concept, lesson, slide deck, or source material into a Feynman learning cycle in which learners explain first, expose the smallest gap, rebuild the explanation through Socratic prompts, strip jargon, stress-test analogies, and transfer the idea to a new context. Use when the user asks for teach-back, learning by explaining, or a Feynman-style classroom. Do not use when the Feynman technique itself is merely the lesson topic or when study strategy should remain a parallel goal."
---

# Feynman Learning

Reorganize any subject into a complete Feynman learning cycle. The central object is the learner's current explanation, rather than the textbook. The learner must explain first, reveal a gap, rebuild the explanation, express it differently, and apply it elsewhere. Finish with a Feynman Learning Record and a goal for the next cycle.

Load `/stage-design` first and follow its procedures for creating a classroom, setting the roster, persisting each page, and checking audio. This skill specifies the pedagogy, page briefs, and interaction rhythm.

## Scope

Use for requests to:

- Learn or teach a specific concept with the Feynman approach.
- Convert slides, lesson plans, videos, or source material into Feynman learning activities.
- Design a classroom around teach-back, self-explanation, probing questions, and transfer.

Do not use for:

- An introductory lesson whose subject is what the Feynman technique is.
- A concept lesson in which study strategies should remain a parallel goal; use `/learning-to-learn` instead.
- Brand-style cloning or faithful PPT import; use `/style-clone` or `/pptx-import`. Imported material can still provide the factual sources for this skill.

## Core principles

1. **The learner speaks before the AI intervenes.** Collect the learner's own explanation before showing an authoritative definition, textbook explanation, or standard procedure. Without an initial explanation, there is no Feynman cycle.
2. **Repair the smallest gap at a time.** Locate the most consequential one or two breaks in the explanation; do not unload the whole textbook onto the learner.
3. **Probe before supplying answers.** Use the fewest questions needed to help the learner rebuild the causal chain. Supply necessary facts or scaffolding only after repeated probing still leaves the learner stuck and the user permits it.
4. **Understanding must survive rewording and transfer.** Recalling terms alone is insufficient. The learner must explain without jargon, identify where an analogy fails, and reconstruct the idea in an unfamiliar setting.
5. **Sources establish facts without replacing the first explanation.** Teacher-provided material defines the conceptual boundary and checks factual accuracy. Do not display it as the standard answer on the opening page.

## Student-facing content boundaries

The following are planning terms. They may appear in the conversation, briefs, and roster design, but not as student-facing titles, labels, or sections: `Teach-back`, `Jargon Challenge`, `Transfer`, `v1/v2/v3`, `Concept boundary`, `Gap diagnosis`, `Analogy stress test`, `Feynman cycle`, and `Conceptual change trajectory`.

Use actionable student-facing titles, for example:

- "Explain it to someone who has never studied it."
- "Where does your explanation get stuck?"
- "Replace these words and explain it again."
- "Where does this analogy stop working?"
- "Try it in a new setting."

Put teacher and student-agent speech, probing, and discussion in narration/actions. Do not write static page-body lines such as "The teacher says" or "The beginner says."

## Establish three constraints

Before planning pages, establish:

1. **Concept boundary:** the learnable core concept covered in this cycle, including what is outside its scope.
2. **Audience:** whom the learner is explaining it to, such as a middle-school student or an outsider who has not studied it.
3. **Teacher constraints:** the intended depth and whether the AI may supply an answer after unsuccessful probing.

Use `ask_user` only when the request does not establish these constraints.

## Map the cycle to pages

The cycle can fit into seven to nine pages. Do not pursue a fixed page count, but preserve the complete evidence chain below. Combine the conceptual boundary and first explanation into an opening `interactive` task, so standard content does not leak before the initial explanation.

### 1. Explain it to an outsider (interactive)

- Briefly establish the concept boundary and target audience without giving the standard definition.
- Ask the learner for a first explanation in their own words, without consulting sources.
- Prefer text or voice input. If the component cannot save free responses, ask the learner to write or speak their version and have teacher narration remind them to retain it for later comparison.

### 2. Find the smallest sticking point (interactive or slide)

- Break the initial explanation into essential conceptual elements.
- Identify only one or two crucial skipped steps, substituted terms, faulty causal links, or omissions.
- Let the learner locate where they are stuck; do not merely display an AI score.

Keep the concept checklist in the brief and turn it into questions the learner can answer. Do not render internal labels such as "Gap 1" and "Gap 2."

### 3. Rebuild the causal chain through questions (interactive, or slide ending with a discussion action)

- Each question addresses one identified gap.
- The beginner agent probes "Why?" and "What would happen if the conditions changed?"
- State in the brief what the question targets and which evidence of understanding ends the probing.
- Do not directly give the answer before the teacher constraints permit it.

### 4. Explain it again (interactive)

- Offer a small amount of structural support and ask for a second explanation.
- Cues must point to the causal structure, rather than repeat the standard answer.
- Retain comparable differences between the first and second explanations for the final learning record.

### 5. Remove the terms you just used (interactive)

- Select terms the learner actually used in their second explanation.
- Ask for another explanation without those terms, or use a counterexample that exposes rote recall.
- Do not show a preset jargon blacklist unrelated to the learner's expression.

### 6. Challenge your own analogy (interactive)

- Ask the learner to propose an analogy and separately explain where it fits and where it does not.
- Elicit at least one point at which the analogy fails.
- Do not prefill every failure point. Let agent questions help the learner discover them.

### 7. Move to an unfamiliar setting (interactive or quiz)

- Apply the concept in a setting not used on earlier pages.
- You may forbid the concept's name to require an explanation through its mechanism.
- Prefer including a counterexample, boundary condition, or changed assumption to check whether the learner understands the structure.

### 8. Assemble the Feynman Learning Record (slide or interactive)

Use the learner's own words. The record must include at least:

1. What I can explain now.
2. How I understood it at first.
3. Where I discovered I was stuck.
4. My revised explanation.
5. My analogy and where it fails.
6. The new problem I can solve.
7. What I still cannot explain and the goal for my next learning cycle.

This is a starting point for the next cycle, rather than a celebration declaring mastery.

## Roster

- **Teacher/coach:** protect the explain-before-feedback sequence, decide when scaffolding is appropriate, and return discussion to the core concept.
- **Beginner agent:** act as the explanation's audience, honestly express what is unclear, and probe causal links. This is the main detector of gaps.
- **Optional misconception agent:** present a common faulty explanation for the learner to distinguish; do not reveal the standard answer early.

## Build and verify

Follow the `/stage-design` sequence: `create_stage` -> `set_roster` -> `generate_scene` page by page according to the approved plan -> `list_scenes` -> `read_stage`. Use `generate_actions` to add or rebuild narration, and ensure all final speech actions have audio. Call `generate_tts` after changing narration text.

Before completion, check each page:

- The first learner explanation precedes all standard content.
- You can explain what each page externalizes, exposes, or rebuilds.
- Diagnosis focuses on only one or two small gaps.
- Probing has not turned into answering for the learner.
- Jargon removal targets the learner's own words.
- The analogy test produces at least one failure point.
- Transfer leaves the original example and includes a boundary or counterexample.
- Static pages contain no planning labels, pedagogical jargon, or role dialogue.
- The final record contains understanding, remaining gaps, and a next-cycle goal.

## Capability boundaries

Generated pages do not dynamically diagnose every sentence of a learner's live input. Use three paths accurately:

1. Collect explanations through `interactive` and offer checkpoints for self-checking.
2. Use roster agents and teacher narration to model Socratic probing.
3. Run the cycle in workbench conversation when sentence-level diagnosis and persistent explanation versions are required; use classroom pages as the activity structure.

Do not describe static or pregenerated pages as real-time grading.
