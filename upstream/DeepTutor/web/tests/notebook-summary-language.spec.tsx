import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import SaveToNotebookModal from "@/components/notebook/SaveToNotebookModal";

const state=vi.hoisted(()=>({language:"zh-CN",saved:[] as Record<string,any>[]}));
vi.mock("react-i18next",()=>({useTranslation:()=>({t:(key:string)=>key,i18n:{language:state.language,resolvedLanguage:state.language}})}));
vi.mock("@/lib/notebook-api",()=>({listNotebooks:vi.fn().mockResolvedValue([{id:"nb-test",name:"Test notebook"}]),createNotebook:vi.fn()}));
vi.mock("@/lib/api",()=>({apiUrl:(url:string)=>url,apiFetch:vi.fn(async (_url:string,init:RequestInit)=>{
  state.saved.push(JSON.parse(String(init.body)));
  return new Response('data: {"type":"result","success":true,"summary":"Saved"}\n\n',{headers:{"Content-Type":"text/event-stream"}});
})}));
afterEach(()=>{cleanup();state.saved=[];vi.unstubAllGlobals();});

for(const language of ["zh-CN","en"]){
  it(`passes the actual ${language} interface language when saving a chat record`,async()=>{
    state.language=language;
    vi.stubGlobal("ResizeObserver",class{observe(){}disconnect(){}});
    render(<SaveToNotebookModal open payload={{recordType:"chat",title:"Test record",userQuery:"Question",output:"Original answer",metadata:{source:"original",ui_language:"obsolete"}}} onClose={()=>{}}/>);
    const dialog=await screen.findByRole("dialog",{name:"Save to Notebook"});
    fireEvent.click(await within(dialog).findByText("Test notebook"));
    fireEvent.click(within(dialog).getByRole("button",{name:"Save",exact:true}));
    await waitFor(()=>expect(state.saved).toHaveLength(1));
    expect(state.saved[0].metadata).toMatchObject({source:"original",ui_language:language});
    expect(state.saved[0].output).toBe("Original answer");
  });
}
