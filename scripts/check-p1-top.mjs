import { chromium } from 'playwright-core';

async function main() {
  const browser = await chromium.connectOverCDP('http://127.0.0.1:9222');
  const context = browser.contexts()[0];
  const pages = context.pages();
  const p1 = pages.find(p => p.url().includes('0e935f47-3f1e-4546-9972-431b328de86f'));
  if (p1) {
    const topBatch = p1.locator('.batch-container').first();
    console.log('Top batch text:', (await topBatch.innerText()).replace(/\n+/g, ' ').slice(0, 200));
    const imgs = await topBatch.locator('img').count();
    console.log('Images in top batch:', imgs);
    for (let i = 0; i < imgs; i++) {
      const src = await topBatch.locator('img').nth(i).getAttribute('src');
      console.log(`Image ${i} src:`, src?.slice(0, 80));
    }
  }
  await browser.close();
}

main().catch(console.error);
