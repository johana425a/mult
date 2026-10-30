import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import ConsultationTabBody from '@/components/chat/home/ConsultationTabBody';
import { PartnerDraftCard } from '@/components/chat/home/PartnerDraftCard';
import { releaseFeatureAvailable, releasePathAvailable } from '@/lib/competition-profile';

vi.mock('react-i18next',()=>({useTranslation:()=>({t:(value:string)=>value})}));
vi.mock('next/navigation',()=>({useRouter:()=>({push:vi.fn()})}));
vi.mock('@/components/partners/PartnerChat',()=>({default:()=>{throw Error('Excluded partner chat mounted');}}));
vi.mock('@/components/partners/group/PartnerGroupChat',()=>({default:()=>{throw Error('Excluded group chat mounted');}}));
vi.mock('@/components/chat/home/SubagentRunTranscript',()=>({default:({events}:any)=><div>{events.map((e:any,i:number)=><p key={i}>{e.content}</p>)}</div>}));
vi.mock('@/components/chat/home/SubagentTabBody',()=>({default:()=> <div>Local agent</div>}));
afterEach(cleanup);

it('blocks all partner entries while retaining the core and imported-agent routes',()=>{
 expect(releaseFeatureAvailable('partners')).toBe(false);
 for(const path of ['/partners','/partners/groups/new','/api/partners/a','/api/partner-groups/a','/ws/partners/a','/ws/partner-groups/a'])expect(releasePathAvailable(path)).toBe(false);
 for(const path of ['/chat','/learning','/education','/agents'])expect(releasePathAvailable(path)).toBe(true);
});
it('retains historical partner discussion text without opening a new failed chat',()=>{
 for(const metadata of [{subagent_kind:'partner',partner_id:'a',partner_session_key:'s'},{partner_group_id:'g',partner_group_session_key:'s'}]){
   render(<ConsultationTabBody tabEvents={[{content:'Saved explanation',metadata} as any]} sessionId="s"/>);
   expect(screen.getByText('Saved explanation')).toBeInTheDocument();cleanup();
 }
 render(<ConsultationTabBody tabEvents={[]} sessionId="s"/>);
 expect(screen.getByText('Local agent')).toBeInTheDocument();
});
it('does not offer confirmation of a preserved partner draft in this edition',()=>{
 render(<PartnerDraftCard data={{draft_id:'a',name:'Tutor',description:'',soul:'',language:'en'} as any}/>);
 expect(screen.queryByRole('button')).not.toBeInTheDocument();
});
