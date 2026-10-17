/** Durable operation identity: uncertain pre-crash effects are never replayed. */
import {mkdir,readFile,writeFile,rename} from 'node:fs/promises';
import {join} from 'node:path';
import {createHash,randomUUID} from 'node:crypto';
const hash = value => createHash('sha256').update(JSON.stringify(value)).digest('hex');
const fail = (code,message) => Object.assign(new Error(message),{code});
export async function createOperationReceipts(profile) {
  const root=join(profile,'operation-receipts'); await mkdir(root,{recursive:true});
  const live=new Map();
  const save=async(path,value)=>{const temp=path+'.'+randomUUID()+'.tmp';await writeFile(temp,JSON.stringify(value),{mode:0o600});await rename(temp,path);};
  async function perform(identity,descriptor,execute,signal) {
    const key=hash(identity), path=join(root,key+'.json'), fingerprint=hash(descriptor);
    let old;
    try{old=JSON.parse(await readFile(path,'utf8'));}catch(error){if(error.code!=='ENOENT')throw error;}
    if(old) {
      if(old.fingerprint!==fingerprint)throw fail('OPERATION_IDENTITY_CONFLICT','This operation identity was already used for different arguments.');
      if(old.status==='completed')return old.result;
      throw fail('OPERATION_OUTCOME_UNCERTAIN','This operation may have changed files before execution stopped. Inspect its saved results and target files before issuing a new operation.');
    }
    signal?.throwIfAborted();
    const record={schema:1,identity,fingerprint,status:'started',started_at:new Date().toISOString()};
    await save(path,record);
    signal?.throwIfAborted();
    const result=await execute();
    await save(path,{...record,status:'completed',completed_at:new Date().toISOString(),result});
    return result;
  }
  return {execute(identity,descriptor,run,signal){
    const key=hash(identity), fingerprint=hash(descriptor), prior=live.get(key);
    if(prior) {
      if(prior.fingerprint!==fingerprint)return Promise.reject(fail('OPERATION_IDENTITY_CONFLICT','This in-flight operation has different arguments.'));
      return prior.job;
    }
    const job=perform(identity,descriptor,run,signal).finally(()=>live.delete(key));
    live.set(key,{fingerprint,job});return job;
  }};
}
