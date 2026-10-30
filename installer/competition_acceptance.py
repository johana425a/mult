"""Competition acceptance policy: skipped or historical evidence cannot release a build."""
import math

KINDS = ('core-flows','fault-recovery','mixed-use','install-lifecycle','feature-coverage')
AI_FLOWS = ('chat_tool','reading_questions','personalized_learning','classroom','documents')
CORE_STEPS = {
    'first_use': ('configure_model','send','tool_result','no_developer_environment'),
    'text_pdf': ('import','index','last_page','source_answer','switch','reopen_position'),
    'scanned_pdf': ('import','index','last_page','source_answer','switch','reopen_position'),
    'large_book': ('import','index','last_page','source_answer','switch','reopen_position'),
    'bilibili': ('connect','complete_subtitles','play','follow','seek','speed','source_answer','five_question_types'),
    'youtube': ('connect','complete_subtitles','play','follow','seek','speed','source_answer','five_question_types'),
    'personalized': ('explain','quiz','wrong_feedback','correct_feedback','save','reopen','no_false_mastery'),
    'classroom': ('generate','edit','play','question','interaction','quiz','save','reopen'),
    'documents': ('chat_export','learning_export','reading_export','classroom_export','md','docx','pdf','xlsx','pptx','download','open','modify','readback','reopen'),
}
FAULTS = ('offline','expired_account','timeout','bad_model_format','subtitle_update','cancel_then_send',
          'double_click','close_reopen','chinese_space_path','readonly_directory','locked_file')
LIFECYCLE = ('fresh_install','first_use','r11_4_install','r11_4_use','upgrade','continue_use','uninstall','reinstall','reopen_retained_data')
SOAK_ACTIONS = ('read','play','ask','quiz','export','navigate')


def need(condition, message):
    if not condition:raise ValueError(message)


def seconds(value):
    return isinstance(value,(float,int)) and not isinstance(value,bool) and math.isfinite(value) and value>=0


def rows_by_id(rows, ids, field='case'):
    need(isinstance(rows,list) and len(rows)==len(ids),'Missing or duplicate acceptance cases')
    need({r.get(field) for r in rows}==set(ids),'Required acceptance case missing')
    return {r[field]:r for r in rows}


def successful(row, checked):
    need(row.get('status')=='passed' and row.get('assertions',0)>0 and not row.get('skipped'),
         'A case failed, was skipped, or made no assertions')
    need(seconds(row.get('total_seconds')),'Missing actual elapsed time')
    checked(row['evidence'])


def verify(kind, row, context, checked, profile):
    if kind=='core-flows':
        need(row.get('evidence_class')=='live-product','Core flows require the real product and real models')
        cases=rows_by_id(row.get('cases'),CORE_STEPS)
        for name,steps in CORE_STEPS.items():
            case=cases[name];successful(case,checked)
            need(case.get('interface') in ('background-browser','native-ui'),'Backend-only output is not UI acceptance')
            need(all(case.get('steps',{}).get(s) is True for s in steps),'Incomplete journey: '+name)
            need(seconds(case.get('first_feedback_seconds')) and case['first_feedback_seconds']<=2,
                 'Local feedback exceeds two seconds: '+name)
        models=context['required_models'];primary=row.get('primary_model')
        need(primary in models,'Primary model is not one of the accepted configured models')
        expected={(model,flow,n) for model in models for flow in AI_FLOWS for n in range(1,4 if model==primary else 2)}
        attempts=row.get('model_rounds',[])
        need(len(attempts)==len(expected) and {(r.get('model'),r.get('flow'),r.get('round')) for r in attempts}==expected,
             'Missing model flow or three consecutive primary rounds')
        for attempt in attempts:
            successful(attempt,checked)
            need(attempt.get('real_model') is True and attempt.get('selection_preserved') is True,'A model was mocked or replaced')
            need(all(seconds(attempt.get(k)) for k in ('model_seconds','tool_seconds')),'Missing model/tool timing')
            need(attempt['total_seconds']>=max(attempt['model_seconds'],attempt['tool_seconds']),'Invalid timing accounting')
            need(attempt.get('execution_id'),'No actual execution identity')
            if attempt['model']==primary:
                need(attempt.get('start_mode')=={1:'cold',2:'warm',3:'reopen'}[attempt['round']],
                     'Primary rounds must include cold start and reopen')
        need(row.get('consecutive_primary_passes') is True,'Primary-model failures were not reset before the three-pass sequence')
    elif kind=='fault-recovery':
        cases=rows_by_id(row.get('cases'),FAULTS)
        for name,case in cases.items():
            successful(case,checked)
            need(case.get('evidence_class') in ('injected-fault','actual-fault'),'Fault evidence must declare its origin')
            need(all(case.get(k) is True for k in ('input_preserved','records_preserved','terminated_or_recoverable','no_duplicate_output','no_false_completion')),
                 'Failure recovery is incomplete: '+name)
    elif kind=='mixed-use':
        need(row.get('evidence_class')=='live-product','A sleep or mock loop is not mixed-use acceptance')
        start=row.get('started_at');end=row.get('finished_at')
        need(seconds(start) and seconds(end) and end-start>=7200,'Mixed use is shorter than two hours')
        events=row.get('samples',[])
        need(len(events)>=61,'Too few continuous health samples')
        timestamps=[sample['timestamp'] for sample in events]
        need(timestamps==sorted(timestamps) and timestamps[0]-start<=120 and end-timestamps[-1]<=120 and
             all(0<b-a<=120 for a,b in zip(timestamps,timestamps[1:])), 'Unobserved gap during mixed use')
        expected={a['sha256'] for a in context['artifacts']}
        for sample in events:
            need(set(sample.get('artifact_sha256s',[]))==expected,'Soak switched candidate artifacts')
            need(all(seconds(sample.get(k)) for k in ('rss_bytes','pending_tasks')),'Missing resource or backlog samples')
            need(sample.get('healthy') is True,'Unhealthy mixed-use sample')
        need(set(row.get('actions',{}))>=set(SOAK_ACTIONS) and all(row['actions'][x]>=3 for x in SOAK_ACTIONS),
             'Soak did not mix the required activities')
        need(row.get('crashes')==0 and row.get('duplicate_records')==0 and row.get('state_errors')==0,
             'Mixed use found crashes, duplication or state errors')
        need(row.get('resource_growth_reviewed') is True and row.get('unbounded_resource_growth') is False,
             'Resource growth has not been investigated')
        checked(row['transcript']);checked(row['resource_report'])
    elif kind=='install-lifecycle':
        need(row.get('evidence_class')=='second-windows-pc','Local empty-directory installation is not second-PC acceptance')
        need(row.get('machine_id') and row['machine_id']!=row.get('build_machine_id'),'Second machine must be distinct')
        need(row.get('architecture')=='x64' and row.get('windows_version'),'Missing actual test-machine environment')
        need(row.get('reviewer') and row.get('no_developer_dependencies') is True,'Fresh-machine use not established')
        need([r.get('case') for r in row.get('cases',[])]==list(LIFECYCLE),'Installation lifecycle incomplete or unordered')
        for case in row['cases']:successful(case,checked)
        need(all(row.get(k) is True for k in ('owned_program_removed','owned_shortcuts_removed','owned_registration_removed','retained_data_verified','new_login_verified')),
             'Uninstall ownership, data retention or login acceptance incomplete')
        checked(row['recording'])
    elif kind=='feature-coverage':
        features={f['id']:f for f in profile['features']}
        cases=rows_by_id(row.get('features'),features,'id')
        for key,feature in features.items():
            case=cases[key]
            need(case.get('enabled') is feature['enabled'],'Manual and shipping feature list differ')
            if feature['enabled']:
                successful(case,checked)
                need(case.get('interface') in ('background-browser','native-ui'),'Visible feature only checked at API level')
                need(all(case.get('steps',{}).get(k) is True for k in ('create_or_open','operate','save','switch','reopen')),
                     'Visible feature lacks complete usage evidence: '+key)
            else:
                need(not feature['core'] and case.get('status')=='hidden_after_failure','A core feature was hidden or peripheral failure was not recorded')
                checked(case['failure_evidence'])
                need(case.get('navigation_actions_and_routes_blocked') is True,'Hidden feature remains reachable')
        checked(row['manual']);checked(row['onboarding']);checked(row['demo_material'])
    else:
        raise ValueError('Unknown competition acceptance kind')
