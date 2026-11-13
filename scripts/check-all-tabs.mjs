import { chromium } from 'playwright-core';

async function main() {
  const browser = await chromium.connectOverCDP('http://127.0.0.1:9222');
  const pages = browser.contexts()[0].pages();
  for (const p of pages) {
    const u = p.url();
    if (u.includes('project')) {
      const topBatch = p.locator('.batch-container').first();
      const text = await topBatch.innerText().catch(() => 'none');
      console.log('Project:', u.split('/').pop());
      console.log('Top batch text:', text.slice(0, 150).replace(/\n+/g, ' '));
      console.log('---');
    }
  }
  await browser.close();
}

main().catch(console.error);
