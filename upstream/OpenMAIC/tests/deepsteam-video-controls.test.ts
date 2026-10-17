import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
const mocks = vi.hoisted(() => ({ saveAs:vi.fn(),build:vi.fn(),stage:{id:'course-test',name:'Course'} }));
vi.mock('file-saver',()=>({saveAs:mocks.saveAs}));
vi.mock('sonner',()=>({toast:{loading:vi.fn(()=>1),error:vi.fn(),success:vi.fn(),info:vi.fn(),warning:vi.fn()}}));
vi.mock('@/lib/store/stage',()=>({useStageStore:{getState:()=>({stage:mocks.stage})}}));
vi.mock('@/lib/video-export-app/observe-export-changes',()=>({observeExportChanges:()=>()=>{}}));
vi.mock('@/lib/video-export-app/resolve-stage-name',()=>({resolveExportStageName:async()=> 'Course'}));
vi.mock('@/lib/video-export-app/build-export-zip',()=>({buildExportZip:mocks.build}));
import { useVideoRenderStore } from '../lib/store/video-render';
const key='deepsteam-video-render-v1';
const t=(key:string)=>key;
const options={resolution:'720p',fps:24,quality:'standard',burnInSubtitles:true};
const answer=(data:unknown,status=200)=>Promise.resolve(new Response(JSON.stringify(data),{status,headers:{'content-type':'application/json'}}));
beforeEach(()=>{
  const memory=new Map<string,string>();
  vi.stubGlobal('localStorage',{getItem:(k:string)=>memory.get(k)||null,setItem:(k:string,v:string)=>memory.set(k,v),removeItem:(k:string)=>memory.delete(k)});
  useVideoRenderStore.setState({status:'idle',jobId:null,error:null,filename:null});
  useVideoRenderStore.getState().reset();
  mocks.saveAs.mockClear(); mocks.build.mockReset();
  mocks.build.mockResolvedValue({zipBlob:new Blob(['zip']),stageName:'Course - selected',missingCount:0,errorCount:0});
});
afterEach(()=>{vi.useRealTimers();vi.unstubAllGlobals();});

describe('video task ownership and recovery',()=>{
  it('cancels an accepted job even when cancellation races its POST response',async()=>{
    let accept!:(response:Response)=>void;
    const request=vi.fn((url:string,init?:RequestInit)=>{
      if(init?.method==='POST') return new Promise<Response>(resolve=>{accept=resolve;});
      if(init?.method==='DELETE') return answer({cancelled:true});
      throw new Error(`Unexpected ${url}`);
    });
    vi.stubGlobal('fetch',request);
    const running=useVideoRenderStore.getState().startRender(t,'en-US',['scene-short']);
    await vi.waitFor(()=>expect(request).toHaveBeenCalled());
    useVideoRenderStore.getState().cancelRender();
    accept(new Response(JSON.stringify({jobId:'accepted-job'}),{status:202}));
    await running;
    expect(request).toHaveBeenCalledWith('/api/export-video/render/accepted-job',{method:'DELETE'});
    expect(useVideoRenderStore.getState().status).toBe('cancelled');
    expect(mocks.saveAs).not.toHaveBeenCalled();
    expect(localStorage.getItem(key)).toBeNull();
    expect(mocks.build.mock.calls[0][0].sceneIds).toEqual(['scene-short']);
  });
  it('resumes the accepted task after reload without POSTing a duplicate',async()=>{
    vi.useFakeTimers();
    localStorage.setItem(key,JSON.stringify({jobId:'existing-job',filename:'existing.mp4',status:'rendering',options,
      selection:{stageId:'course-test',sceneIds:['scene-short']}}));
    const request=vi.fn((url:string,_init?:RequestInit)=>url.endsWith('/download')
      ? Promise.resolve(new Response(new Blob(['mp4']))) : answer({status:'succeeded',progress:1}));
    vi.stubGlobal('fetch',request);
    const running=useVideoRenderStore.getState().restoreRender(t);
    await vi.advanceTimersByTimeAsync(3000); await running;
    expect(request.mock.calls.every(call=>!call[1]?.method || call[1].method==='GET')).toBe(true);
    expect(mocks.build).not.toHaveBeenCalled();
    expect(mocks.saveAs).toHaveBeenCalledOnce();
    expect(useVideoRenderStore.getState().status).toBe('succeeded');
    expect(JSON.parse(localStorage.getItem(key)!).status).toBe('succeeded');
    expect(useVideoRenderStore.getState().selection).toEqual({stageId:'course-test',sceneIds:['scene-short']});
    expect(JSON.parse(localStorage.getItem(key)!).selection.sceneIds).toEqual(['scene-short']);
  });
  it('keeps a completed video downloadable after another page load',async()=>{
    localStorage.setItem(key,JSON.stringify({jobId:'completed-job',filename:'done.mp4',status:'succeeded',options}));
    const request=vi.fn();vi.stubGlobal('fetch',request);
    await useVideoRenderStore.getState().restoreRender(t);
    expect(useVideoRenderStore.getState().jobId).toBe('completed-job');
    expect(useVideoRenderStore.getState().status).toBe('succeeded');
    expect(request).not.toHaveBeenCalled();
  });
});
