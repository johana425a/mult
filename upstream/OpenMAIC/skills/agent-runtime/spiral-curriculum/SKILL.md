---
name: spiral-curriculum
title: "Spiral Curriculum Design"
description: "Design a multi-stage OpenMAIC course series around a small concept spine whose ideas return repeatedly at higher levels of complexity, abstraction, relationship density, representation, transfer distance, or boundary awareness. Use when the user explicitly wants a Bruner-style spiral curriculum, progressive conceptual revisits, or a series organized by how understanding develops rather than by a linear topic list. Do not use for a single standalone stage or a series that only needs sequential coverage."
---

# Spiral Curriculum Design

Design a course series in which a few core concepts return throughout the series and gain structural depth each time. The smallest design object is a concept spine plus each concept's encounter history, rather than one lesson's contents list.

Load `/stage-design` for the baseline classroom-creation procedure and `/curriculum-planner` for course folders, reading across classrooms, and batch delivery. This skill adds spiral architecture, growth operators, and checks for false spirals.

## Scope

Use for requests to:

- Design a unit or series using Bruner's spiral curriculum.
- Revisit the same core concepts across lessons with progressively deeper understanding.
- Organize lessons around the development of understanding rather than a linear textbook chapter order.

Do not use for:

- One standalone lesson; use `/stage-design` and the appropriate subject skill.
- Sequential coverage without concept growth on revisits; use `/curriculum-planner`.
- Style cloning or direct PPT import; use `/style-clone` or `/pptx-import`.

## First principle: revisit is not review

Teaching a concept in lesson 1, reviewing it in lesson 3, and reviewing it again in lesson 6 does not make a spiral. Each revisit must answer: **What does this encounter add to the previous one?**

Every revisit must advance at least one dimension:

| Dimension | First encounter | Later revisit |
| --- | --- | --- |
| Complexity | A single relationship | Interactions among several variables |
| Abstraction | A concrete example | A general model |
| Relationship density | An isolated concept | Connections to more concepts |
| Representation | Intuitive experience | Diagrams, models, and symbols |
| Transfer distance | A familiar setting | An unfamiliar or cross-disciplinary setting |
| Boundaries and counterexamples | Positive examples | Counterexamples, conditions, and limitations |

If a return advances none of these dimensions, it is repetition and must be rewritten.

## Student-facing content boundaries

`Concept Spine`, `encounter`, `growth operator`, `Spiral Contract`, `revisit`, `encounter history`, and the `●/▲/◆` markers are teacher-side planning language. They may appear in the conversation, architecture, and page briefs, but not in student-facing titles, labels, or body text.

Record what this encounter adds in the brief; do not label student pages "Complexity upgrade." Put teacher and agent speech in narration/actions, rather than static "Teacher says" or "Student says" text.

## Concept spine

Do not begin with a timetable. First ask which reusable, transferable core ideas learners should build by the end of the series.

- Express each core concept as a transferable understanding in a sentence, rather than a noun.
- A series usually uses three to six concepts; too many lead to shallow treatment in every lesson.
- Give each concept an initial and a final understanding target as the endpoints of Learner Progression.
- You may use `/understanding-by-design` to establish big ideas, essential questions, and performance evidence before arranging deeper revisits across lessons.

## Spiral Map

Maintain an encounter history for every concept: intuitive experience -> mechanism -> multivariable relationships -> formal model -> unfamiliar transfer -> integration with other concepts.

The teacher-side Spiral Map may use:

- `●`: first encounter.
- `▲`: deepening.
- `◆`: integration and transfer.

Every marker must also state the structure added at that encounter. A table of symbols without growth explanations has no design value.

## Plan a revisit

For each `concept + previous encounter + target growth`, make four decisions:

1. **Retain:** which existing understanding does not need reteaching.
2. **Add:** what content or conditions are new.
3. **Reorganize:** which isolated facts must form a mechanism or relationship.
4. **Transfer:** which new setting tests the concept's structure.

## Growth operators

- **ADD_COMPLEXITY:** add variables or interactions.
- **ADD_RELATION:** establish a necessary relationship with another concept.
- **ABSTRACT:** move from an example to a general model.
- **FORMALIZE:** introduce symbols, models, or professional language.
- **CHANGE_REPRESENTATION:** reconstruct the concept across actions, visual models, and symbols; do not mechanically assign these to a fixed lesson sequence.
- **INCREASE_TRANSFER_DISTANCE:** move gradually into less familiar or cross-disciplinary settings.
- **ADD_EXCEPTION:** introduce counterexamples, boundaries, constraints, or limitations.

Usually choose one main operator and a few supporting operators for a revisit. Applying every operator at once merely piles on difficulty.

## Concept memory

A spiral depends on shared memory across stages. The platform does not automatically maintain a concept model for this skill. Keep a teacher-side running record in the current conversation with at least:

- Concept ID.
- Encounter history.
- Representation history.
- Complexity level.
- Known relationships.
- Detected misconceptions.
- Examples already used.
- Transfer distance.
- Evidence of mastery.
- Target for the next revisit.

Before beginning the next lesson, use `read_stage_outline` to read the persisted page lists from earlier classrooms, and `read_stage` when actual content needs checking. Do not rely solely on the original plan. Adjust what to retain, add, reorganize, and transfer according to the content actually saved.

## A Spiral Contract for each lesson

Every stage must have a teacher-side contract containing:

- `returning_concepts`: concepts that return.
- `new_concepts`: concepts appearing for the first time.
- `added_complexity`: what becomes more complex or abstract.
- `new_relation`: the new relationship between concepts.
- `representation_shift`: whether the representation changes.
- `transfer_target`: the new setting.
- `future_hook`: what is deliberately left for a later revisit.

The `future_hook` allows productive incompleteness: build a usable but incomplete model early and reorganize it later. Each lesson need not finish the entire concept.

## Two layers of design

### Layer 1: Spiral Architecture

Produce these in the conversation and ask the user to confirm them:

1. **Concept Spine:** initial and final understanding targets for every core concept.
2. **Course Timeline:** each lesson's topic and tasks.
3. **Concept Spiral Map:** first appearances, returns, and what each encounter adds.
4. **Learner Progression:** how understanding should change from lesson to lesson.
5. Every lesson's Spiral Contract and intersections between concepts.

Use `ask_user` so the user can adjust lesson count, timing of concept encounters, depth, and cross-concept relationships. Do not create classrooms before the architecture is confirmed.

### Layer 2: Generate Lessons

After approval, continue building the entire approved series to completion. Do not repeatedly stop for confirmation between lessons unless the user explicitly asks for batch reviews.

1. Create the course folder with `create_folder`.
2. Call `create_stage` for each lesson, passing that `folderId`.
3. Call `set_roster` before `generate_scene` page by page according to the approved plan.
4. Use `generate_actions` for missing narration and `generate_tts` after narration changes.
5. Verify the persisted results with `list_scenes`, `read_stage_outline`, and `read_stage`.
6. Update concept memory before starting each later classroom.

Keep the architecture in teacher-side planning; do not generate it as student pages.

## Check for false spirals

After completing the series, inspect each concept for:

- **Repeated, not spiraled:** multiple appearances without increased complexity.
- **Vocabulary inflation:** more terms without deeper structural understanding.
- **Linear curriculum:** every lesson has new content and previous concepts never return.
- **Review curriculum:** the only return occurs at the end of the unit.
- **Context repetition:** the same setting and representation on each return.
- **Difficulty escalation without conceptual deepening:** harder questions without deeper concepts.

If any check fails, revise the relevant Spiral Contract, page briefs, or course schedule and verify again.

## Completion criteria

- Every concept has initial and final understanding targets and a complete encounter history.
- Each revisit identifies its main growth operator and added structure.
- Every lesson has a seven-field Spiral Contract.
- The architecture is approved first; the entire approved series is then persisted into its folder.
- Every lesson's actual content has been read back; concept memory does not rely solely on plans.
- Student-facing text contains no spiral metadata, planning jargon, or role dialogue.
- Every classroom still meets `/stage-design` requirements for pages, roster, persistence, and audio.
- The series passes the false-spiral checks.

## Relationship to other pedagogies

- `/understanding-by-design` can establish big ideas, essential questions, and performance assessments; this skill arranges deeper revisits across lessons.
- `/feynman-learning` externalizes and rebuilds explanations within one classroom; this skill arranges the return of concepts across an entire series.
- `/learning-to-learn` and `/social-emotional-learning` are parallel goals. Embed them only when they serve the current revisit, without creating a separate course storyline.
