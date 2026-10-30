import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import NotebookConsole from '@/components/notebook/NotebookConsole';

const mocks=vi.hoisted(()=>({push:vi.fn(),replace:vi.fn(),create:vi.fn(),select:vi.fn(),remove:vi.fn()}));
vi.mock('next/navigation',()=>({useRouter:()=>({push:mocks.push,replace:mocks.replace})}));
vi.mock('react-i18next',()=>({useTranslation:()=>({t:(key:string)=>key})}));
vi.mock('@/components/notebook/NotebookRecordRow',()=>({default:()=>null}));
vi.mock('@/components/notebook/useNotebookLibrary',()=>({useNotebookLibrary:()=>({
 notebooks:[{id:'saved-1',name:'Saved first',record_count:0},{id:'saved-2',name:'Saved second',record_count:0}],
 selectedId:'saved-1',selected:{id:'saved-1',name:'Saved first',records:[]},
 loading:false,detailLoading:false,error:null,detailError:null,
 select:mocks.select,create:mocks.create,remove:mocks.remove,reload:vi.fn(),rename:vi.fn(),
 editRecord:vi.fn(),removeRecord:vi.fn(),relocateRecord:vi.fn(),
})}));
beforeEach(()=>{vi.clearAllMocks();window.history.replaceState({},'', '/notebooks?dt_workspace=ws_original');});
afterEach(cleanup);

it('keeps the store when canonicalizing a default notebook selection',()=>{
 render(<NotebookConsole/>);
 expect(mocks.replace).toHaveBeenCalledWith('/notebooks/saved-1?dt_workspace=ws_original');
});

it('keeps the original store after a delayed create finishes across navigation',async()=>{
 let finish!:(id:string)=>void;
 mocks.create.mockImplementation(()=>new Promise(resolve=>{finish=resolve;}));
 render(<NotebookConsole initialNotebookId="saved-1"/>);
 fireEvent.click(screen.getByRole('button',{name:'New notebook',exact:true}));
 fireEvent.change(screen.getByPlaceholderText('Notebook name'),{target:{value:'中文 学习记录'}});
 fireEvent.click(screen.getByRole('button',{name:'Create',exact:true}));
 fireEvent.keyDown(screen.getByPlaceholderText('Notebook name'),{key:'Enter'});
 expect(mocks.create).toHaveBeenCalledTimes(1);
 expect(screen.getByRole('button',{name:'Create',exact:true})).toBeDisabled();
 expect(mocks.create).toHaveBeenCalledWith('中文 学习记录','');
 window.history.replaceState({},'', '/notebooks?dt_workspace=ws_other');
 finish('created-1');
 await waitFor(()=>expect(mocks.push).toHaveBeenCalledWith('/notebooks/created-1?dt_workspace=ws_original'));
});

it('opens existing notes in the same workspace and retains the course filter',()=>{
 render(<NotebookConsole initialNotebookId="saved-1" courseScope={{id:'course 1',name:'Course',notebookIds:['saved-1','saved-2']}}/>);
 fireEvent.click(within(screen.getByRole('navigation')).getByRole('button',{name:/Saved second/}));
 expect(mocks.select).toHaveBeenCalledWith('saved-2');
 expect(mocks.push).toHaveBeenCalledWith('/notebooks/saved-2?course=course+1&dt_workspace=ws_original');
});

it('retains an explicitly selected default workspace',()=>{
 window.history.replaceState({},'', '/notebooks?dt_workspace=');
 render(<NotebookConsole/>);
 expect(mocks.replace).toHaveBeenCalledWith('/notebooks/saved-1?dt_workspace=');
});
