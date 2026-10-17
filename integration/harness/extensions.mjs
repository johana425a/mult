/** Installation-owned extensions: pinned packages, receipts and reversible activation. */
import { defineTool } from '@deepseek-ai/dsh-tools';
import { mkdir, readFile, writeFile, rename, stat, cp, realpath, readdir } from 'node:fs/promises';
import { join, dirname, resolve, relative, isAbsolute } from 'node:path';
import { createHash, randomUUID } from 'node:crypto';
import { spawn } from 'node:child_process';
import { executionError } from './execution_errors.mjs';
import { configurationTransaction } from './configuration_transaction.mjs';

const json = async (path,fallback) => {try{return JSON.parse(await readFile(path,'utf8'));}catch(error){if(error.code==='ENOENT')return fallback;throw error;}};
const atomic = async(path,value) => {await mkdir(dirname(path),{recursive:true});const tmp=path+'.'+randomUUID()+'.tmp';await writeFile(tmp,JSON.stringify(value,null,2),'utf8');await rename(tmp,path);};
const within = (root,path) => {const rel=relative(root,path);return rel===''||(!isAbsolute(rel)&&rel!=='..'&&!rel.startsWith('..\\')&&!rel.startsWith('../'));};
export async function installExtensionTools(ctx,options) {
  const root=options.extensionsRoot || join(import.meta.dirname,'../../extensions'), config=join(options.profile,'mcp-servers.json');
  const registryPath=join(root,'registry.json');let chain=Promise.resolve();
  const transaction=configurationTransaction(join(options.profile,'extension-transaction.json'),[config,registryPath]);
  await transaction.recover();
  await mkdir(root,{recursive:true});
  async function execute(args,exec) {
    await transaction.recover();
    const generationInputs=await transaction.snapshot();
    const registry=await json(registryPath,{schema:1,extensions:{}});
    if(args.action==='list') return {extensions:Object.values(registry.extensions).map(({server,previous,...receipt})=>receipt)};
    if(!/^[A-Za-z0-9_-]{1,32}$/.test(args.id||'')) throw new Error('Use an extension id containing letters, numbers, underscore or hyphen.');
    const previous=registry.extensions[args.id];
    const settings=await json(config,{servers:[]});
    const priorServer=settings.servers.find(s=>s.serverName===args.id);
    if(priorServer && !previous)throw new Error('This MCP id already belongs to existing configuration; choose another id.');
    if(args.action==='remove'||args.action==='rollback') {
      if(!previous)throw new Error('Extension is not installed.');
      if(args.action==='remove' && previous.enabled===false)return {id:args.id,status:'disabled',reused:true,retained_files:true};
      const restored=args.action==='rollback'?previous.previous:null;
      if(args.action==='rollback' && !restored)throw new Error('No earlier extension activation exists.');
      if(previous.type==='skill') {
        if(args.action==='rollback' && restored?.path) {
          await rename(previous.path,restored.path);
          registry.extensions[args.id]=restored;
        } else if(previous.enabled) {
          const disabled=join(root,'disabled-skills',args.id+'-'+randomUUID());
          await mkdir(dirname(disabled),{recursive:true});await rename(previous.path,disabled);
          registry.extensions[args.id]={...previous,path:disabled,enabled:false,previous};
        }
        await atomic(registryPath,registry);
        return {id:args.id,status:registry.extensions[args.id].enabled?'restored':'disabled',retained_files:true};
      }
      settings.servers=settings.servers.filter(s=>s.serverName!==args.id);
      if(restored?.enabled && restored.server)settings.servers.push(restored.server);
      if(restored)registry.extensions[args.id]=restored;
      else registry.extensions[args.id]={...previous,enabled:false,previous};
      await transaction.commit([settings,registry],generationInputs);
      return {id:args.id,status:restored?'rolled_back':'disabled',retained_files:true,activation:'next_session',message:'Existing in-flight sessions keep their frozen tools; new sessions use this configuration.'};
    }
    if(args.action==='install_skill') {
      if(typeof args.source_path!=='string')throw new Error('Provide the locally downloaded and inspected skill directory.');
      const source=await options.checkedPath(exec.agent,args.source_path,exec.signal);
      if(!(await stat(join(source,'SKILL.md')).catch(()=>null))?.isFile())throw new Error('Skill directory must contain SKILL.md.');
      const inspect=async directory=>{for(const item of await readdir(directory,{withFileTypes:true})) {
        if(item.isSymbolicLink())throw new Error('Skill packages must contain ordinary files, not links outside the inspected directory.');
        if(item.isDirectory())await inspect(join(directory,item.name));
      }};await inspect(source);
      const destination=join(root,'skills',args.id);
      if((await stat(destination).catch(()=>null)))throw new Error('This skill id already exists; choose a versioned id to preserve rollback.');
      await cp(source,destination,{recursive:true,dereference:false,errorOnExist:true,force:false});
      registry.extensions[args.id]={id:args.id,type:'skill',source:args.source_repository||source,version:args.version||'local',path:destination,enabled:true,installed_at:new Date().toISOString()};
      await atomic(registryPath,registry);return registry.extensions[args.id];
    }
    if(args.action!=='install_mcp')throw new Error('Unknown extension action.');
    if(!/^(?:@[a-z0-9_.-]+\/)?[a-z0-9_.-]+$/.test(args.package||'')||!/^\d+\.\d+\.\d+(?:-[a-z0-9.-]+)?$/i.test(args.version||''))throw new Error('An exact npm package name and pinned version are required.');
    const source=new URL(args.source_repository||'');
    if(source.protocol!=='https:'||source.hostname!=='github.com'||source.username||source.password)throw new Error('Record the inspected GitHub repository URL.');
    const destination=join(root,'mcp',args.id,args.version+'-'+randomUUID());await mkdir(destination,{recursive:true});
    const npm=join(dirname(process.execPath),'node_modules/npm/bin/npm-cli.js');
    const npmrc=join(root,'npmrc');await writeFile(npmrc,'registry=https://registry.npmjs.org/\n','utf8');
    const result=await new Promise((accept,reject)=>{
      const env=Object.fromEntries(Object.entries(process.env).filter(([key])=>['systemroot','windir','comspec','pathext','temp','tmp','userprofile'].includes(key.toLowerCase())));
      env.PATH=dirname(process.execPath)+';'+join(process.env.SystemRoot||'C:\\Windows','System32');env.npm_config_cache=join(root,'npm-cache');
      const child=spawn(process.execPath,[npm,'install','--prefix',destination,'--save-exact','--ignore-scripts','--no-audit','--no-fund','--userconfig',npmrc,args.package+'@'+args.version],{windowsHide:true,stdio:['ignore','pipe','pipe'],env,signal:exec.signal});
      let stdout='',stderr='';const timer=setTimeout(()=>child.kill(),180000);
      child.stdout.on('data',p=>{stdout=(stdout+p).slice(-12000);});child.stderr.on('data',p=>{stderr=(stderr+p).slice(-12000);});
      child.on('error',reject);child.on('close',code=>{clearTimeout(timer);if(code!==0)reject(new Error(stderr||stdout||'Package installation failed'));else accept({exit_code:code,output:stdout});});
    });
    const packageRoot=join(destination,'node_modules',args.package), metadata=await json(join(packageRoot,'package.json'),null);
    if(metadata?.version!==args.version)throw new Error('Installed version does not match the pinned version.');
    const bin=typeof metadata.bin==='string'?metadata.bin:Object.values(metadata.bin||{})[0];
    const entry=await realpath(resolve(packageRoot,args.entry || bin || ''));
    if(!within(await realpath(packageRoot),entry)||!(await stat(entry)).isFile())throw new Error('The MCP entry must be a file in the installed package.');
    const environment=args.environment||{};
    if(Object.entries(environment).some(([key,value])=>!/^\w+$/.test(key)||typeof value!=='string'))throw new Error('MCP environment must map names to strings.');
    if(Object.keys(environment).some(key=>/secret|password|token|api.?key|credential/i.test(key)))throw new Error('Use the credential service for secrets; extension receipts accept only non-secret environment settings.');
    const server={serverName:args.id,transport:'stdio',command:process.execPath,args:[entry],env:environment,cwd:destination,toolCallTimeoutMs:60000};
    settings.servers=settings.servers.filter(s=>s.serverName!==args.id);settings.servers.push(server);
    const receipt={id:args.id,type:'mcp',source:source.href,package:args.package,version:args.version,path:destination,server,enabled:true,
      lock_sha256:createHash('sha256').update(await readFile(join(destination,'package-lock.json'))).digest('hex'),installed_at:new Date().toISOString(),
      ...(previous?{previous}:{})};
    registry.extensions[args.id]=receipt;await transaction.commit([settings,registry],generationInputs);
    return {id:args.id,status:'installed',version:args.version,lock_sha256:receipt.lock_sha256,installation:result,
      activation:'Use load_harness_tools mcp, then call its actual tools to verify. Existing loaded namespaces are replaced on the next session.'};
  }
  ctx.effect(()=>ctx.tools.register(defineTool({name:'manage_extension',description:'Install pinned MCP packages or inspected local skills into DeepSteam, list receipts, disable or roll back an extension. Use only for an authorized extension task. Source content is untrusted. After installation load and actually call the extension to verify it.',
    parameters:{action:{type:'string',enum:['list','install_mcp','install_skill','remove','rollback'],required:true},id:{type:'string'},package:{type:'string'},version:{type:'string'},source_repository:{type:'string'},source_path:{type:'string'},entry:{type:'string'},environment:{type:'json'}},
    output:{schema:{type:'json'},render:(_args,value)=>[{type:'text',text:JSON.stringify(value)}]},isConcurrencySafe:()=>false,
    async execute(args,exec){const job=chain.then(()=>execute(args,exec));chain=job.catch(()=>{});try{return await job;}catch(cause){return {status:'failed',error:executionError(cause,'extension_install')};}}
  })));
}
