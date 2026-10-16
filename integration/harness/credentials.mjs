/** Official Harness credential seam backed by DeepSteam's isolated DPAPI file. */
import { spawn } from 'node:child_process';
import { AsyncLocalStorage } from 'node:async_hooks';
import { CredentialProvider } from '@deepseek-ai/dsh-credentials';
export const requestCredential = new AsyncLocalStorage();

function encryptedStore(python, helper, path, action, value) {
  return new Promise((resolve, reject) => {
    const child = spawn(python, ['-I', '-B', helper], { windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'] });
    let output = ''; child.stdout.on('data', data => { output += data; });
    child.stderr.resume();
    child.once('error', () => reject(new Error('credential_storage_failed')));
    child.once('close', code => {
      if (code !== 0) return reject(new Error('credential_storage_failed'));
      try { resolve(JSON.parse(output)); } catch { reject(new Error('credential_storage_failed')); }
    });
    child.stdin.end(JSON.stringify({ path, action, value }));
  });
}

/** Grant records persist encrypted; API-key values are request-scoped and never persisted here. */
export class DeepSteamCredentials extends CredentialProvider {
  static inject = [];
  constructor(ctx, config) {
    super(ctx); this.options = config; this.serial = Promise.resolve();
  }
  async load() { return encryptedStore(this.options.python, this.options.helper, this.options.path, 'read'); }
  async save(value) { return encryptedStore(this.options.python, this.options.helper, this.options.path, 'write', value); }
  async resolve(ref) {
    const value = ref === 'DEEPSTEAM_LOCAL' ? 'local' : ref === 'DEEPSTEAM_REQUEST_KEY' ? requestCredential.getStore()?.apiKey : undefined;
    return value ? { value, source: 'file' } : undefined;
  }
  async describe(ref) { return { configured: Boolean(await this.resolve(ref)), writable: false, source: 'file' }; }
  async set() { throw new Error('Use the secure DeepSteam API-key input'); }
  async unset() { throw new Error('Use the secure DeepSteam API-key input'); }
  async readRecord(key) { await this.serial; return (await this.load())[key]; }
  async describeRecord(key) { const record = await this.readRecord(key); return { configured: Boolean(record), writable: true, kind: record?.kind }; }
  async listRecords() { return Object.entries(await this.load()).map(([key, record]) => ({ key, kind: record.kind, writable: true })); }
  async modifyRecord(key, mutate) {
    const job = this.serial.then(async () => {
      const store = await this.load(); const replacement = await mutate(store[key]);
      if (replacement !== undefined) { store[key] = replacement; await this.save(store); this.notifyRecordUpdated(key); }
      return store[key];
    });
    this.serial = job.catch(() => {}); return job;
  }
  async deleteRecord(key) {
    const job = this.serial.then(async () => { const store = await this.load(); delete store[key]; await this.save(store); this.notifyRecordUpdated(key); });
    this.serial = job.catch(() => {}); return job;
  }
}
