// DeepSteam: renderer-only view snapshots across route-group remounts.
// No conversation titles are stored on disk. Scope and auth invalidation apply.
function store() {
  if (typeof window === 'undefined') return {rows:new Map(),listeners:new Set(),generation:0};
  const key=Symbol.for('deepsteam.sidebar.view.v2');
  return window[key] || (window[key]={rows:new Map(),listeners:new Set(),generation:0});
}
function scopedKey(key) {
  const query=new URLSearchParams(typeof window==='undefined'?'':window.location.search);
  return JSON.stringify([query.get('dt_workspace') ?? query.get('workspace') ?? '',key]);
}
function read(key) {return store().rows.get(scopedKey(key));}
function has(key) {return read(key)!==undefined;}
function clear() {
  const current=store();current.generation++;current.rows.clear();
  for(const listener of [...current.listeners])listener();
}
function useRetained(React,key,initial) {
  const initialRef=React.useRef(initial),current=store(),cacheKey=scopedKey(key),generation=current.generation;
  const alive=React.useRef(true);
  React.useEffect(()=>{alive.current=true;return()=>{alive.current=false;};},[]);
  const subscribe=React.useCallback(listener=>{
    current.listeners.add(listener);return()=>current.listeners.delete(listener);
  },[current]);
  const snapshot=React.useCallback(()=>current.rows.has(cacheKey)?current.rows.get(cacheKey):initialRef.current,[current,cacheKey]);
  const serverSnapshot=React.useCallback(()=>initialRef.current,[]);
  const value=React.useSyncExternalStore(subscribe,snapshot,serverSnapshot);
  const update=React.useCallback(next=>{
    if(!alive.current || current.generation!==generation || cacheKey!==scopedKey(key))return;
    const before=current.rows.has(cacheKey)?current.rows.get(cacheKey):initialRef.current;
    const resolved=typeof next==='function'?next(before):next;
    if(Object.is(before,resolved)&&current.rows.has(cacheKey))return;
    current.rows.set(cacheKey,resolved);
    for(const listener of [...current.listeners])listener();
  },[current,cacheKey,generation,key]);
  return [value,update];
}
module.exports={read,has,clear,useRetained};
