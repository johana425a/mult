import {defineTool} from '@deepseek-ai/dsh-tools';
import {spawn} from 'node:child_process';
import {join,resolve} from 'node:path';
import {executionError} from './execution_errors.mjs';

export async function installRepairTools(ctx, options) {
  let chain=Promise.resolve();
  ctx.effect(()=>ctx.tools.register(defineTool({name:'manage_repair',
    description:'Stage a reversible source repair, execute a real check against its isolated staged files, queue application repairs for restart, and roll back. Do not overwrite running application files. Use an isolated application copy to exercise repair and rollback. A check must actually test the changed behavior.',
    parameters:{action:{type:'string',enum:['list','stage','verify','apply','rollback'],required:true},id:{type:'string'},target_root:{type:'string'},files:{type:'json',description:'Array of relative path and UTF-8 content objects.'},command:{type:'json',description:'Validation executable and arguments as an array; use bundled runtime paths.'},timeout:{type:'integer'}},
    output:{schema:{type:'json'},render:(_args,value)=>[{type:'text',text:JSON.stringify(value)}]},isConcurrencySafe:()=>false,
    async execute(args,exec){
      const operation=chain.then(async()=>{
        if(args.action==='stage'){
          const root=await options.checkedPath(exec.agent,args.target_root,exec.signal);
          for(const file of args.files||[])await options.checkedPath(exec.agent,resolve(root,file.path),exec.signal);
        }
        return new Promise((accept,reject)=>{
          const child=spawn(options.python,[join(import.meta.dirname,'../../scripts/repair_bundle.py')],{windowsHide:true,stdio:['pipe','pipe','pipe'],signal:exec.signal,env:{...process.env,PYTHONUTF8:'1'}});
          let stdout='',stderr='';
          child.stdout.on('data',p=>{stdout+=p.toString('utf8');});child.stderr.on('data',p=>{stderr+=p.toString('utf8');});
          child.on('error',reject);child.on('close',code=>{try{const result=JSON.parse(stdout);if(code!==0||!result.ok)throw new Error(result.error||stderr);accept(result.result);}catch(error){reject(error);}});
          child.stdin.end(JSON.stringify(args));
        });
      });
      chain=operation.catch(()=>{});
      try{return await operation;}catch(cause){return {status:'failed',error:executionError(cause,'repair')};}
    }
  })));
}
