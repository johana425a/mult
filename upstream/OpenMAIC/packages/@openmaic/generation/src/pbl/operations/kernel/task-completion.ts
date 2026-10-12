import type {
  PBLChatMessage,
  PBLEvaluation,
  PBLInternalAssessment,
  PBLMilestone,
  PBLMicrotask,
  PBLPendingTaskCompletion,
  PBLProjectV2,
} from '../../types.js';
import { recordEvent } from './engagement.js';
import {
  appendRuntimeEvent,
  milestoneIdForMicrotask,
  mintRuntimeEventId,
} from './runtime-events.js';
import { trimmedPBLText } from '../../readers.js';

export const TASK_EVAL_PASS_SCORE = 60;

export function taskEvaluationCanComplete(evaluation: PBLEvaluation | undefined): boolean {
  return (
    evaluation?.kind === 'task' &&
    typeof evaluation.score === 'number' &&
    evaluation.score >= TASK_EVAL_PASS_SCORE
  );
}

export function orderedMicrotasks(milestone: PBLMilestone): PBLMicrotask[] {
  return milestone.microtasks.slice().sort((a, b) => a.order - b.order);
}

export function isLastMicrotaskOfMilestone(milestone: PBLMilestone, microtaskId: string): boolean {
  const tasks = orderedMicrotasks(milestone);
  return tasks.length > 0 && tasks[tasks.length - 1]?.id === microtaskId;
}

export function isCoreMilestoneFinalMicrotask(
  milestone: PBLMilestone,
  microtaskId: string,
): boolean {
  return !!milestone.synthesisCheck && isLastMicrotaskOfMilestone(milestone, microtaskId);
}

export function currentPendingTaskCompletion(
  project: PBLProjectV2,
  microtaskId: string | undefined,
): PBLPendingTaskCompletion | undefined {
  if (!microtaskId) return undefined;
  const pending = project.pendingTaskCompletion;
  return pending?.microtaskId === microtaskId ? pending : undefined;
}

export function setPendingTaskCompletion(
  project: PBLProjectV2,
  args: {
    microtaskId: string;
    milestoneId: string;
    reason: string;
    assessment?: PBLInternalAssessment;
    evidence?: PBLPendingTaskCompletion['evidence'];
  },
): PBLPendingTaskCompletion {
  const existing = currentPendingTaskCompletion(project, args.microtaskId);
  const pending: PBLPendingTaskCompletion = {
    microtaskId: args.microtaskId,
    milestoneId: args.milestoneId,
    reason: args.reason,
    assessment: args.assessment,
    evidence: args.evidence,
    createdAt: existing?.createdAt ?? new Date().toISOString(),
  };
  project.pendingTaskCompletion = pending;
  appendRuntimeEvent(project, {
    id: mintRuntimeEventId(),
    kind: 'task_completion_staged',
    actorType: 'system',
    reason: pending.reason,
    ts: pending.createdAt,
    microtaskId: pending.microtaskId,
    milestoneId: pending.milestoneId,
  });
  project.updatedAt = new Date().toISOString();
  return pending;
}

export function taskCompletionReadyText(language: string | undefined): string {
  switch (language) {
    case 'zh-CN':
      return 'This task is complete. When you are ready and have no other questions, click Done on the current task in the left sidebar to move on.';
    case 'zh-TW':
      return 'This task is complete. When you are ready and have no other questions, click Done on the current task in the left sidebar to move on.';
    case 'ja-JP':
      return 'This task is complete. When you are ready and have no other questions, click Done on the current task in the left sidebar to move on.';
    case 'ru-RU':
      return 'This task is complete. When you are ready and have no other questions, click Done on the current task in the left sidebar to move on.';
    case 'ar-SA':
      return 'This task is complete. When you are ready and have no other questions, click Done on the current task in the left sidebar to move on.';
    case 'en-US':
    default:
      return 'This task is complete. When you are ready and have no other questions, click Done on the current task in the left sidebar to move on.';
  }
}

const TASK_COMPLETION_READY_TEXTS = new Set(
  ['zh-CN', 'zh-TW', 'ja-JP', 'ru-RU', 'ar-SA', 'en-US', undefined].map((language) =>
    taskCompletionReadyText(language),
  ),
);

export function isTaskCompletionReadyMessageContent(content: unknown): boolean {
  return TASK_COMPLETION_READY_TEXTS.has(trimmedPBLText(content));
}

function isoAfter(previous?: string): string {
  const now = Date.now();
  const previousMs = previous ? Date.parse(previous) : NaN;
  const min = Number.isFinite(previousMs) ? previousMs + 1 : 0;
  return new Date(Math.max(now, min)).toISOString();
}

export function appendTaskCompletionReadyMessage(
  project: PBLProjectV2,
  microtaskId: string,
  options: { afterTs?: string } = {},
): PBLChatMessage | undefined {
  const instructor = project.roles.find((r) => r.type === 'instructor');
  if (!instructor) return undefined;
  const thread = project.threads.find((t) => t.agentId === instructor.id);
  if (!thread) return undefined;
  const content = taskCompletionReadyText(project.language);
  const exists = thread.messages.some(
    (m) => m.microtaskId === microtaskId && m.content === content,
  );
  if (exists) return undefined;
  const message: PBLChatMessage = {
    id: 'msg_' + Date.now().toString(16) + Math.random().toString(16).slice(2, 6),
    agentId: instructor.id,
    roleType: 'instructor',
    content,
    ts: isoAfter(options.afterTs),
    microtaskId,
  };
  thread.messages.push(message);
  appendRuntimeEvent(project, {
    id: mintRuntimeEventId(),
    kind: 'message_created',
    actorType: 'agent',
    actorRoleId: instructor.id,
    messageId: message.id,
    threadId: thread.agentId,
    ts: message.ts,
    microtaskId: message.microtaskId,
    milestoneId: milestoneIdForMicrotask(project, message.microtaskId),
  });
  project.updatedAt = message.ts;
  return message;
}

export function recordPendingTaskCompletionEvidence(
  project: PBLProjectV2,
  milestone: PBLMilestone,
  microtask: PBLMicrotask,
  evidence: PBLPendingTaskCompletion['evidence'] | undefined,
): void {
  if (!evidence) return;
  recordEvent(project, 'observation_concept_unlocked', {
    microtaskId: microtask.id,
    milestoneId: milestone.id,
    payload: {
      signature: evidence.signature,
      label: evidence.label,
      note: evidence.note,
    },
  });
}

export function clearPendingTaskCompletion(project: PBLProjectV2, microtaskId?: string): void {
  if (!project.pendingTaskCompletion) return;
  if (microtaskId && project.pendingTaskCompletion.microtaskId !== microtaskId) return;
  const pending = project.pendingTaskCompletion;
  delete project.pendingTaskCompletion;
  appendRuntimeEvent(project, {
    id: mintRuntimeEventId(),
    kind: 'task_completion_cleared',
    actorType: 'system',
    ts: new Date().toISOString(),
    microtaskId: pending.microtaskId,
    milestoneId: pending.milestoneId,
  });
  project.updatedAt = new Date().toISOString();
}
