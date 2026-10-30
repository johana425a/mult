"""DeepSteam quiz-plan compatibility and bounded contract validation."""
from collections import Counter
from deeptutor.utils.json_parser import parse_json_response

TYPE_ALIASES = {
    'multiple_choice': 'choice', 'single_choice': 'choice', 'mcq': 'choice',
    'true_false': 'concept', 'true_or_false': 'concept', 'boolean': 'concept',
    'fill_blank': 'fill_in_blank', 'fill_in_the_blank': 'fill_in_blank',
    'short-answer': 'short_answer', 'essay': 'written', 'programming': 'coding',
    '选择题': 'choice', '单选题': 'choice', '判断题': 'concept',
    '填空题': 'fill_in_blank', '简答题': 'short_answer', '论述题': 'written', '编程题': 'coding',
}


class QuizPlanningError(RuntimeError):
    error_code = 'quiz_plan_invalid'
    phase = 'planning'
    retryable = False


def plan_payload(raw):
    """Accept equivalent JSON envelopes, never invent missing topic content."""
    data = parse_json_response(raw, fallback={})
    if isinstance(data, list):
        return '', data
    if not isinstance(data, dict):
        return '', []
    if isinstance(data.get('plan'), dict):
        data = data['plan']
    for key in ('templates', 'ideas', 'questions'):
        if isinstance(data.get(key), list):
            return str(data.get('analysis') or ''), data[key]
    return '', []


def plan_issues(plan, step, requested, counts):
    problems = []
    if step.reasoning_only:
        problems.append('No final plan was returned.')
    if step.finish_reason in {'length', 'max_tokens', 'max_output_tokens'} or step.stream_idle_timeout:
        problems.append('The plan response was truncated or its stream did not finish.')
    if len(plan.templates) != requested:
        problems.append(f'Expected exactly {requested} valid, distinct templates; received {len(plan.templates)}.')
    actual = Counter(t.question_type for t in plan.templates)
    if counts and actual != Counter(counts):
        problems.append(f'The type distribution must be exactly {dict(counts)}; received {dict(actual)}.')
    return problems
