---
name: zone-of-proximal-development
description: "Design a coherent assessment-and-practice lesson using zone-of-proximal-development principles: independent diagnosis, targeted review, supported practice, fresh independent checks, and an evidence-based next step. Use for practice lessons based on the zone of proximal development, diagnostic review lessons, or guided-to-independent practice. Can also run one practice cycle in chat; do not turn a request for a single exercise or theory explanation into a full lesson."
metadata:
  title: "Practice Lesson (Zone of Proximal Development)"
  version: "0.2.0-experimental"
---

# Practice Lesson (Zone of Proximal Development)

Organize existing learning content into an assessment-and-practice lesson, rather than merely generating questions. An independent attempt locates the difficulty to address; targeted review and temporary support help the learner continue; a fresh task checks performance and informs the next practice step. A teacher or more experienced peer provides support while the learner gradually assumes the key judgments and actions.

The zone of proximal development is a theoretical concept concerning development and assistance. The diagnostic attempts, scaffolding, and fading below are this skill's instructional design, rather than a fixed procedure proposed by Vygotsky. One activity provides clues about performance under particular tasks and support conditions; it does not measure a stable ZPD score.

Read [Theoretical basis and design translation](references/theory.md) when checking theoretical attribution or explaining the design rationale.

## Choose a mode

- **Create or improve a complete practice lesson:** read [Organizing a complete assessment-and-practice lesson](references/exercise-lesson.md). Load `/stage-design` for a new classroom. For an existing classroom, inventory it with `/pro-editing` before completing missing parts. This skill governs whole-lesson goals, relationships among tasks, review, practice paths, and closure; it does not replace page tools.
- **One exercise, a task set, or practice in the current conversation:** run a learning cycle within the requested scope, receiving a response before deciding each next step. Do not expand it into a full lesson or create a classroom unasked.
- **A theory question only:** answer the theoretical question without forcing diagnosis, practice, or classroom creation.

Infer the learner, prior learning, lesson duration, core goal, success criteria, and prerequisites from the request and sources. Ask only when missing information would materially change the teaching. Organize practice around one practicable goal, such as solving a class of equations, revising an argument paragraph, or making a code change. Necessary reteaching serves that goal rather than expanding into comprehensive new instruction.

## Organize the whole lesson first

The plan explains what learners should be able to do at the end, what each task group checks or practices, and where earlier performance changes the support. Goals, diagnosis, review, supported practice, independent checking, and closure must connect. They may share pages; increasing the question count does not make a complete practice lesson.

Review the learner's actual work. Label pregenerated typical errors as teaching examples, rather than "the mistake you just made." Learners who can already perform and justify their work may skip guided practice. Those needing more support may return to prerequisite tasks. Without automatic routing at runtime, provide clear learner- or teacher-selected paths and actual navigation instructions; do not claim the system already selected one.

## Begin with independent performance

Give a short task directly related to the goal at an appropriate difficulty, and ask for an attempt and the reason for a key step. Start from existing authentic work when sufficient. Do not show the target solution, hints, or correct answer before the first attempt. Record conditions when providing necessary accessibility support for reading, language, or input.

Do not infer ability directly from self-identification as a beginner, grade level, one wrong answer, or the accuracy of one item. Observe the response: is essential knowledge missing, is procedural execution difficult, is the task unclear, or is evidence insufficient? Ask one distinguishing question only when those interpretations require different help.

Keep diagnostic questions focused. If a later sentence in the same turn reveals the earlier answer, that earlier question is no longer independent evidence. For example, after asking whether `2x` means addition or multiplication, wait for the answer before saying to multiply by two and then add three.

Connect evidence and interpretation with "You wrote ..., which may mean ..." Do not invent an unspoken mental state or claim that one item directly measures the ZPD.

Describe the task and support conditions rather than locating the learner "inside the ZPD," "at its edge," or at a developmental ceiling. A self-reported difficulty alone cannot justify such a label.

- If the learner succeeds independently with reasonable justification, reduce support, use a slightly changed task, or finish without forcing guided practice.
- If the learner cannot yet act independently, offer proportionate help for the observed obstacle.
- If there is no attempt or the response is unclear, invite a feasible small action and postpone ability judgments.

## Provide help according to the response

Choose the support most likely to let the learner continue. Do not make everyone climb the same ladder:

| Current obstacle | Possible support | Action still left to the learner |
| --- | --- | --- |
| An important condition went unnoticed | Point toward the condition or ask a directional question | Identify the relationship and choose the next step |
| The concept is known but there are too many steps | A step card, diagram, or partly completed task | Complete the key step and explain why |
| Essential knowledge or a method is missing | Brief explicit instruction, using another example if needed | Apply the method to the target task |
| Repeated failure or evident frustration | Narrow the goal, return to a prerequisite, or change representation | Complete a smaller action that still has learning value |

Offer one usable piece of help, leave a clear response opportunity, and wait. Do not finish the learner's entire reasoning and answer in the same reply and then announce independence.

When demonstrating, explain why an expert chooses that step and how the result is checked. Prefer another example so the learner retains the key action in the current task. If the user explicitly asks for the solution, explain it, mark that task as "answer seen," and select a new task for independent checking.

An AI peer may model questions, collaborative reasoning, or distinguishable approaches. Its answers are teaching materials, rather than learner performance. Use one primary helper at a time so agents do not offer competing hints simultaneously.

## Fade support and try independently

After receiving an actual supported response, decide which help to maintain, increase, or remove. Fading depends on the learner taking over the key action that previously required help, rather than turning a page or reaching a repetition count.

Use a new task with comparable goal demands. Remove the cues and demonstrations that supplied the key judgment. Do not give the new answer in advance or treat a paraphrase of the original item as independent application. Restore targeted support or return to a smaller goal if the learner gets stuck again.

For the first check after fading, keep required knowledge, key steps, and difficulty similar. Prefer changed values or surface settings. Do not simultaneously introduce untaught rules, such as negative or fractional coefficients after practice with positive-integer equations. Label increased difficulty as a new challenge and check prerequisites separately.

Check whether the demonstration, supported task, and fresh task happen to share the same answer. Avoid passing merely by copying the previous result; judge independence with reasons or key actions too.

Report performance only after receiving the fresh attempt. One success supports a statement such as "You completed this item without step hints." It does not establish stable mastery, retention, or a general developmental level.

## Keep a minimal learning record

Briefly record what actually happened in the conversation:

- The task and the learner's exact initial words or work.
- The help actually given and whether the target answer was seen.
- What the learner personally completed after receiving help.
- What support was removed and what occurred on the new task.
- Whether the next step is independent practice, continued support, reteaching, or stopping for now.

Keep attempts that have not happened pending. Without a response, do not prefill success, misconceptions, or progress. Favor verifiable work and actions over fixed ability labels.

Questions such as which operation to perform on both sides and by how much are themselves support. Record an answer after such a cue as "completed after step prompts." Only a fresh task without these key cues counts as an independent attempt. Bound conclusions to the particular item; do not declare complete mastery of the whole class of problems.

## Implement in OpenMAIC pages

Complete goals, review, and closure according to [Practice lesson organization](references/exercise-lesson.md). The practice cycle can use three activity types, without imposing a fixed page count:

1. **Try first (`quiz` or `interactive`):** collect the independent attempt and provide a clear submission point before the answer appears.
2. **Use a little help if needed (`interactive`, with a short `slide` if necessary):** offer selectable hints or another worked example under clear conditions. The learner still completes the target action after help.
3. **Your turn on a new task (`quiz` or `interactive`):** remove key cues and give a fresh task; retain actual attempts and next-step choices in closure.

Each page brief specifies the task, success criteria, help and its display timing, and the learner's own actions. Narration, AI peers, and default-expanded regions on independent pages must not reveal the solution or answer. Use actionable wording such as "Try one first," "Give me a hint," and "Try a new one on my own."

Prefer one free-response item for independent diagnosis, collecting both the answer and its reason. Read the actual generated questions and the entire page to check types and leakage: another question's stem, choices, or example can reveal the current answer. A brief saying "do not leak" is not proof that the page complies. Repair type mismatches or cross-item leakage in the saved page using `/stage-dsl` quiz guidance, then check classroom preview again.

Generated pages can predefine hints, collect input, and support self-checking. This skill alone cannot make them understand arbitrary free text or decide fading across pages. Run dynamic judgments in workbench conversation. If a page only supports learner-selected help, describe it as that rather than claiming it has diagnosed the learner's ZPD.

For saved responses, use the actual recording mechanism of the component and test submission, retrieval, revision, and refresh. If persistence is not established, tell learners to retain their response elsewhere; do not create a save-success button without implementation. Report classroom generation and learner-cycle completion separately.

## Acceptance priorities

- Goals, diagnosis, review, practice, checking, and next steps align; question or page counts do not replace lesson design.
- Independent and supported attempts are distinguishable and genuinely come from the learner.
- Support addresses observed obstacles and can include teaching when knowledge is missing.
- The learner retains key cognitive actions and has response opportunities.
- Already-capable learners can skip guidance; stuck learners can restore support.
- Fresh tasks reduce key cues, and conclusions remain within the observed conditions.
- Claims about page generation, selected help, dynamic feedback, and learning outcomes match actual capabilities.
