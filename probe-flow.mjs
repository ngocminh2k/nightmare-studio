import { chromium } from 'playwright-core';
const ports = process.argv.slice(2).map(Number);
for (const port of ports) {
  try {
    const b = await chromium.connectOverCDP(`http://127.0.0.1:${port}`);
    const ctx = b.contexts()[0];
    const p = await ctx.newPage();
    await p.goto('https://flow.google.com/', { waitUntil: 'domcontentloaded', timeout: 45000 });
    await p.waitForTimeout(6000);
    const url = p.url();
    const text = (await p.evaluate(() => document.body.innerText)).slice(0, 700);
    const credit = text.match(/(\d+)\s*(credit|tín dụng)/gi);
    console.log(`\n=== ${port} ===\nURL: ${url}\nCREDIT: ${credit}\nTEXT: ${text.replace(/\n+/g,' | ').slice(0,400)}`);
    await p.close();
    await b.close();
  } catch (e) { console.log(port, 'ERR', e.message.split('\n')[0]); }
}
