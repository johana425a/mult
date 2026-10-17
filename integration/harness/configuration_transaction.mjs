/** Recoverable multi-file configuration publication, with edit conflict checks. */
import {readFile,writeFile,mkdir,rename} from 'node:fs/promises';
import {dirname} from 'node:path';
import {createHash,randomUUID} from 'node:crypto';
const encode=value=>JSON.stringify(value,null,2);
const digest=value=>value===null?null:createHash('sha256').update(value).digest('hex');
const read=async path=>{try{return await readFile(path,'utf8');}catch(error){if(error.code==='ENOENT')return null;throw error;}};
const atomic=async(path,data)=>{await mkdir(dirname(path),{recursive:true});const temp=path+'.'+randomUUID()+'.tmp';await writeFile(temp,data,{mode:0o600});await rename(temp,path);};
export function configurationTransaction(journalPath,paths,{afterWrite=()=>{}}={}) {
  async function recover() {
    const raw=await read(journalPath);if(!raw)return;
    const transaction=JSON.parse(raw);if(transaction.status==='committed')return;
    if(transaction.rows.length!==paths.length||transaction.rows.some((row,i)=>row.path!==paths[i]))throw new Error('Extension transaction target mismatch');
    for(const row of transaction.rows) {
      const current=digest(await read(row.path));
      if(current!==row.before&&current!==digest(row.after))throw new Error('Extension configuration changed outside its pending transaction');
    }
    for(const [index,row] of transaction.rows.entries()) {
      if(digest(await read(row.path))!==digest(row.after))await atomic(row.path,row.after);
      await afterWrite(index);
    }
    await atomic(journalPath,encode({...transaction,status:'committed',completed_at:new Date().toISOString()}));
  }
  return {recover,async snapshot(){return Promise.all(paths.map(read));},async commit(values,expected) {
    await recover();
    if(values.length!==paths.length)throw new Error('Extension transaction value mismatch');
    const generation=randomUUID();
    const rows=[];
    for(let index=0;index<paths.length;index++) {
      const current=await read(paths[index]);
      if(expected && current!==expected[index])throw new Error('Extension configuration changed while installation was in progress');
      rows.push({path:paths[index],before:digest(current),after:encode({...values[index],deepsteam_generation:generation})});
    }
    await atomic(journalPath,encode({generation,status:'prepared',rows}));
    await recover();return generation;
  }};
}
