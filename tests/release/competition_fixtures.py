"""Synthetic gate test objects only. Never use these as product acceptance."""
import time
import competition_acceptance as policy


def fixtures(context,desc,profile):
    passed={'status':'passed','assertions':1,'total_seconds':1,'evidence':desc}
    primary=context['required_models'][0]
    rounds=[]
    for model in context['required_models']:
        for flow in policy.AI_FLOWS:
            for index in range(1,4 if model==primary else 2):
                rounds.append({**passed,'model':model,'flow':flow,'round':index,'real_model':True,
                    'selection_preserved':True,'model_seconds':0.5,'tool_seconds':0.1,
                    'execution_id':'synthetic-unit-fixture','start_mode':{1:'cold',2:'warm',3:'reopen'}[index]})
    end=time.time();start=end-7200
    return {
      'core-flows':{'passed':True,'evidence_class':'live-product','primary_model':primary,'consecutive_primary_passes':True,
        'cases':[{**passed,'case':name,'interface':'background-browser','first_feedback_seconds':0.1,
                  'steps':{s:True for s in steps}} for name,steps in policy.CORE_STEPS.items()], 'model_rounds':rounds},
      'fault-recovery':{'passed':True,'cases':[{**passed,'case':name,'evidence_class':'injected-fault',
          **{key:True for key in ('input_preserved','records_preserved','terminated_or_recoverable','no_duplicate_output','no_false_completion')}} for name in policy.FAULTS]},
      'mixed-use':{'passed':True,'evidence_class':'live-product','started_at':start,'finished_at':end,
        'samples':[{'timestamp':start+i*120,'artifact_sha256s':[r['sha256'] for r in context['artifacts']],
                    'rss_bytes':1000,'pending_tasks':0,'healthy':True} for i in range(61)],
        'actions':{x:3 for x in policy.SOAK_ACTIONS},'crashes':0,'duplicate_records':0,'state_errors':0,
        'resource_growth_reviewed':True,'unbounded_resource_growth':False,'transcript':desc,'resource_report':desc},
      'install-lifecycle':{'passed':True,'evidence_class':'second-windows-pc','machine_id':'synthetic-other-pc',
        'build_machine_id':'synthetic-build-pc','architecture':'x64','windows_version':'synthetic-fixture',
        'reviewer':'unit-test-only','no_developer_dependencies':True,'cases':[{**passed,'case':n} for n in policy.LIFECYCLE],
        **{key:True for key in ('owned_program_removed','owned_shortcuts_removed','owned_registration_removed','retained_data_verified','new_login_verified')},'recording':desc},
      'feature-coverage':{'passed':True,'features':[
          {**passed,'id':f['id'],'enabled':True,'interface':'background-browser',
           'steps':{k:True for k in ('create_or_open','operate','save','switch','reopen')}} if f['enabled'] else
          {'id':f['id'],'enabled':False,'status':'hidden_after_failure','failure_evidence':desc,
           'navigation_actions_and_routes_blocked':True}
          for f in profile['features']],
          'manual':desc,'onboarding':desc,'demo_material':desc}}
