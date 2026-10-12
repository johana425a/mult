---
name: understanding-by-design
title: "Understanding by Design (UbD)"
description: "Use Understanding by Design (UbD) to plan one OpenMAIC classroom or a course series around transferable conceptual understanding. Use when the user wants backward design, enduring understandings, essential questions, GRASPS performance evidence, WHERETO learning experiences, or a concept-centered lesson rather than a list of facts. Do not use for visual style cloning, teacher-style imitation, or direct PPT import."
---

# Understanding by Design (UbD)

Use UbD backward design for one lesson or a series: first establish what learners should ultimately understand and what would demonstrate understanding, then design the learning experiences.

`stage-design` still governs persistence order for new classrooms. This skill governs instructional design and page-brief content. Use `pro-editing` for local edits to an existing classroom rather than rebuilding it.

## Establish the design scope

- **Standalone lesson:** complete all three stages within the lesson.
- **Unit or course series:** establish unit-level big ideas, overarching essential questions, and a performance task first. Then derive each lesson's supporting understandings, questions, and assessments. Obtain approval of the unit blueprint before drafting individual lessons.

Use `ask_user` to confirm scope only if the request does not establish whether it is a single lesson or a series.

## Stage 1: identify desired results

1. State one to three sentences of **Enduring Understanding**: ideas learners can retain and transfer after leaving the classroom, rather than a facts list.
2. Write one or two **Essential Questions**: open questions that invite continuing discussion, have no unique answer, and can be revisited throughout the course.
3. Open the first page with an essential question, turning the abstract concept into a real problem to investigate.

## Stage 2: determine assessment evidence first

Before planning pages, define how learners will demonstrate understanding:

- **GRASPS performance task:** specify Goal, Role, Audience, Situation, Product, and Standards. Prefer a `pbl` page in OpenMAIC.
- **Concept diagnosis and discrimination:** use `quiz` to expose common misconceptions, requiring reasons rather than selections alone.
- **Transfer and application:** use `interactive` or a new-context task to observe whether learners can apply their understanding to a changed problem.

The performance task is the destination of the learning path. Earlier pages must prepare its concepts, evidence, or practice. Do not introduce an unprepared task at the end.

## Stage 3: design experiences with WHERETO

Check each activity against WHERETO and capture it in the page brief:

- **W - Where & Why:** learners understand the destination and why it is worth learning.
- **H - Hook:** an authentic situation or conflict introduces the essential question.
- **E - Equip:** `slide` provides the evidence and causal or logical chain needed to build the concept.
- **E - Experience:** `interactive` lets learners manipulate, simulate, or construct the concept.
- **R - Rethink & Revise:** a changed setting prompts application and revision of understanding.
- **T - Tailor:** provide scaffolds and challenges for different starting points.
- **O - Organize:** order pages so understanding develops and returns to the essential question.

## OpenMAIC page rhythm

Start with the sequence below if helpful, but adapt it to the required performance evidence rather than applying a fixed template:

1. `slide`: the essential question and an authentic setting.
2. `slide`: evidence or a logical chain that establishes the concept.
3. `interactive`: learners construct the core concept through action.
4. `quiz` or `interactive`: discrimination, transfer, or revision in a new setting.
5. `pbl`: the GRASPS performance task.
6. `quiz` and a closing `slide`: check the concept and return to the essential question.

Use inquiry questions or authentic situations for titles, rather than a textbook contents list. Use English by default; follow an explicitly requested course language.

## Quality gates

- State the big ideas, essential questions, GRASPS task, and WHERETO coverage explicitly.
- Every page must explain which understanding or essential question it serves. Remove or rewrite pages that cannot.
- Abstract concepts require `interactive` or `pbl` work in which learners act, judge, or create, rather than only listen.
- Obtain approval of a unit blueprint before generating a series; do not skip overall design and begin batch generation.

## Boundaries

Do not use for brand-style cloning, imitation of a teacher's delivery style, layout-only cloning, or direct PPT import. Use the corresponding style, teacher-style, or `pptx-import` workflow instead.
