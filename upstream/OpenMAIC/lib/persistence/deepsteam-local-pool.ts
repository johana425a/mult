/** Single-process embedded Postgres for the standalone application's stores.
 * A checked-out client owns the database mutex until release, so requests can
 * never interleave inside another request's BEGIN/COMMIT transaction.
 */
import * as nodeModule from 'node:module';
import {join} from 'node:path';
import {mkdirSync} from 'node:fs';
import {EventEmitter} from 'node:events';
import type {Pool} from 'pg';

export function createDeepSteamLocalPool(connectionString: string): Pool {
  const root=process.env.DEEPSTEAM_APP_ROOT;
  if(!root)throw new Error('The embedded database requires an installation root.');
  // Keep this require rooted in the installed runtime. Webpack rewrites direct
  // createRequire(dynamicPath) calls to an undefined expression at build time.
  const makeRequire=Reflect.get(nodeModule,'createRequire') as typeof nodeModule.createRequire;
  const localRequire=makeRequire(join(root,'runtime/pglite/package.json'));
  const {PGlite}=localRequire('@electric-sql/pglite');
  const directory=connectionString.slice('pglite:'.length);
  mkdirSync(directory,{recursive:true});
  const database=new PGlite(directory);
  let tail=Promise.resolve();
  const acquire=async()=>{const previous=tail;let release!:()=>void;tail=new Promise<void>(done=>{release=done;});await previous;return release;};
  const query=async(text:string|{text:string;values?:unknown[]},values?:unknown[])=>{
    await database.waitReady;
    const sql=typeof text==='string'?text:text.text;
    const parameters=values || (typeof text==='object'?text.values:undefined);
    // The PG schema bootstrap may send several statements without parameters.
    const rows=parameters?.length ? [await database.query(sql,parameters)] : await database.exec(sql);
    const result=rows.at(-1) || {rows:[],fields:[],affectedRows:0};
    return {...result,rowCount:result.affectedRows ?? result.rows?.length ?? 0};
  };
  const pool=new EventEmitter() as EventEmitter & Record<string,unknown>;
  pool.query=async(text:string,values?:unknown[])=>{const release=await acquire();try{return await query(text,values);}finally{release();}};
  pool.connect=async()=>{const unlock=await acquire();let released=false;return {
    query,release(){if(!released){released=true;unlock();}},on(){return this;},removeListener(){return this;},
  };};
  pool.end=async()=>{const release=await acquire();try{await database.close();}finally{release();}};
  return pool as unknown as Pool;
}
