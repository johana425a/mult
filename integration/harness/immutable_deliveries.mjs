/** Content-addressed delivery snapshots; validation and download use identical bytes. */
import {mkdir,readFile,writeFile,rename,stat} from 'node:fs/promises';
import {join,basename,extname} from 'node:path';
import {createHash,randomUUID} from 'node:crypto';
export const DELIVERY_MAX_BYTES=64*1024*1024;
const sha=data=>createHash('sha256').update(data).digest('hex');
const fail=(code)=>Object.assign(new Error(code),{code,status:409});
export async function createImmutableDeliveries(profile,validate) {
  const root=join(profile,'delivery-snapshots'), catalog=join(root,'catalog.json');
  await mkdir(root,{recursive:true});
  let records={};try{records=JSON.parse(await readFile(catalog,'utf8'));}catch(error){if(error.code!=='ENOENT')throw error;}
  let writes=Promise.resolve();
  const save=()=>{const data=JSON.stringify(records);const job=writes.then(async()=>{const temp=catalog+'.'+randomUUID()+'.tmp';await writeFile(temp,data,{mode:0o600});await rename(temp,catalog);});writes=job.catch(()=>{});return job;};
  return {
    get(key){return records[key];},
    async capture(key,paths,signal) {
      if(records[key])return records[key];
      const files=[];
      for(const path of paths) {
        signal?.throwIfAborted();
        const info=await stat(path);
        if(!info.isFile()||info.size===0)throw fail('DELIVERABLE_EMPTY');
        if(info.size>DELIVERY_MAX_BYTES)throw fail('DELIVERABLE_TOO_LARGE');
        const bytes=await readFile(path);
        if(bytes.length>DELIVERY_MAX_BYTES||bytes.length===0)throw fail('DELIVERABLE_SIZE_CHANGED');
        const digest=sha(bytes), extension=extname(path).toLowerCase();
        if(extension&&!/^\.[a-z0-9_-]+$/.test(extension))throw fail('DELIVERABLE_EXTENSION_INVALID');
        const snapshot=join(root,digest+extension);
        const temp=snapshot+'.'+randomUUID()+'.tmp';
        await writeFile(temp,bytes,{mode:0o600});await rename(temp,snapshot);
        const [metadata]=await validate([snapshot],signal);
        if(metadata.sha256!==digest||metadata.size_bytes!==bytes.length)throw fail('DELIVERABLE_VALIDATION_CHANGED');
        files.push({...metadata,filename:basename(path),path,delivery_id:digest+extension,snapshot_path:snapshot});
      }
      records[key]=files;await save();return files;
    },
    async read(key,index) {
      const file=records[key]?.[index];if(!file)throw fail('DELIVERABLE_SNAPSHOT_MISSING');
      const path=join(root,file.delivery_id);
      if(!/^[a-f0-9]{64}(?:\.[a-z0-9_-]+)?$/.test(file.delivery_id))throw fail('DELIVERABLE_SNAPSHOT_INVALID');
      const binary=await readFile(path);
      if(binary.length!==file.size_bytes||sha(binary)!==file.sha256)throw fail('DELIVERABLE_SNAPSHOT_CHANGED');
      return {file,binary};
    }
  };
}
