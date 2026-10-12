// EduAgent diagnostic: launch an isolated, blank browser profile only.
import puppeteer from 'puppeteer-core';
import path from 'node:path';
import fs from 'node:fs/promises';
const local = path.resolve('.local');
await fs.mkdir(path.join(local, 'browser-diagnostic'), { recursive: true });
const browser = await puppeteer.launch({
  executablePath: 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  headless: true,
  timeout: 20000,
  dumpio: true,
  userDataDir: path.join(local, 'browser-diagnostic'),
  env: { ...process.env, TEMP: path.join(local, 'temp'), TMP: path.join(local, 'temp') },
});
console.log(JSON.stringify({ browser: await browser.version() }));
const page = await browser.newPage();
await page.setContent('<h1>Isolated local renderer diagnostic</h1>');
await page.screenshot({ path: path.join(local, 'browser-diagnostic.png') });
await browser.close();
