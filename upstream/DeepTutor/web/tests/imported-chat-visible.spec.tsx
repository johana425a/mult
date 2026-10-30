import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import MyAgentsSection from '@/components/space/MyAgentsSection';
import { readImportMeta } from '@/lib/chat-import/attribution';

const mocks=vi.hoisted(()=>({push:vi.fn(),setActiveSessionId:vi.fn(),list:vi.fn()}));
vi.mock('next/navigation',()=>({useRouter:()=>({push:mocks.push})}));
vi.mock('react-i18next',()=>({useTranslation:()=>({t:(key:string)=>key,i18n:{language:'en'}})}));
vi.mock('@/context/AppShellContext',()=>({useAppShell:()=>({activeSessionId:null,setActiveSessionId:mocks.setActiveSessionId})}));
vi.mock('@/lib/imports-api',()=>({listImportedSessions:mocks.list,importChatHistory:vi.fn()}));
vi.mock('@/lib/chat-import/agent-store',()=>({getAgents:()=>Promise.resolve([]),deleteAgent:vi.fn(),ensureReadPermission:vi.fn(),saveAgent:vi.fn()}));
vi.mock('@/components/SessionList',()=>({default:({sessions,onSelect}:any)=><div>{sessions.map((s:any)=><button key={s.id} onClick={()=>onSelect(s.id)}>{s.title}</button>)}</div>}));
const imported:any={id:'imported_chatgpt_test',session_id:'imported_chatgpt_test',title:'Imported study record',created_at:1,updated_at:2,message_count:2,preferences:{import:{source:'chatgpt',external_id:'test'}}};
beforeEach(()=>{vi.clearAllMocks();window.history.replaceState({},'', '/agents?dt_workspace=study');mocks.list.mockResolvedValue([imported]);});
afterEach(cleanup);

it('shows persisted ChatGPT exports and reopens them in their source workspace',async()=>{
 render(<MyAgentsSection/>);
 fireEvent.click(await screen.findByText('ChatGPT'));
 fireEvent.click(await screen.findByRole('button',{name:'Imported study record'}));
 expect(mocks.setActiveSessionId).toHaveBeenCalledWith('imported_chatgpt_test');
 expect(mocks.push).toHaveBeenCalledWith('/chat/imported_chatgpt_test?dt_workspace=study');
 cleanup();render(<MyAgentsSection/>);
 await waitFor(()=>expect(screen.getByText('ChatGPT')).toBeInTheDocument());
});

it('recognizes all supported import sources and rejects unknown metadata',()=>{
 for(const source of ['chatgpt','claude_code','codex'])expect(readImportMeta({...imported,preferences:{import:{source}}})?.source).toBe(source);
 expect(readImportMeta({...imported,preferences:{import:{source:'unknown'}}})).toBeNull();
 expect(readImportMeta({...imported,preferences:{}})).toBeNull();
});
