import { fireEvent, render, screen, waitFor, cleanup } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import CoWriterHomePage from '@/app/(workspace)/co-writer/page';
import { createCoWriterDocument, importCoWriterDocx, listCoWriterDocuments } from '@/lib/co-writer-api';

const { push }=vi.hoisted(()=>({push:vi.fn()}));
vi.mock('next/navigation',()=>({useRouter:()=>({push})}));
vi.mock('react-i18next',()=>({useTranslation:()=>({t:(key:string)=>key})}));
vi.mock('@/lib/co-writer-events',()=>({notifyCoWriterChanged:vi.fn()}));
vi.mock('@/lib/co-writer-api',()=>({createCoWriterDocument:vi.fn(),importCoWriterDocx:vi.fn(),listCoWriterDocuments:vi.fn(),deleteCoWriterDocument:vi.fn()}));
beforeEach(()=>{vi.clearAllMocks();window.history.replaceState({},'', '/co-writer?dt_workspace=ws_original');vi.mocked(listCoWriterDocuments).mockResolvedValue([]);});
afterEach(cleanup);

it('keeps the creation scope when a delayed save finishes after navigation',async()=>{
 let finish!:(doc:any)=>void;
 vi.mocked(createCoWriterDocument).mockImplementation(()=>new Promise(resolve=>{finish=resolve;}));
 render(<CoWriterHomePage/>);
 fireEvent.click((await screen.findAllByRole('button',{name:'New draft'}))[0]);
 await waitFor(()=>expect(createCoWriterDocument).toHaveBeenCalledTimes(1));
 window.history.replaceState({},'', '/co-writer?dt_workspace=ws_other');
 finish({id:'created-1',title:'Created',content:'',created_at:1,updated_at:1});
 await waitFor(()=>expect(push).toHaveBeenCalledWith('/co-writer/created-1?dt_workspace=ws_original'));
});

it('opens an existing scoped document from its card',async()=>{
 vi.mocked(listCoWriterDocuments).mockResolvedValue([{id:'existing-1',title:'Saved draft',preview:'original note',created_at:1,updated_at:1}]);
 render(<CoWriterHomePage/>);
 fireEvent.click(await screen.findByText('Saved draft'));
 expect(push).toHaveBeenCalledWith('/co-writer/existing-1?dt_workspace=ws_original');
});

it('retains the same store when importing Word',async()=>{
 vi.mocked(importCoWriterDocx).mockResolvedValue({id:'imported-1',title:'Imported',content:'note',created_at:1,updated_at:1});
 const {container}=render(<CoWriterHomePage/>);
 fireEvent.change(container.querySelector('input[type="file"]')!,{target:{files:[new File(['fixture'],'中文 笔记.docx')]}});
 await waitFor(()=>expect(push).toHaveBeenCalledWith('/co-writer/imported-1?dt_workspace=ws_original'));
});
