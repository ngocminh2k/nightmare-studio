import { chromium } from 'playwright-core';

async function main() {
  const browser = await chromium.connectOverCDP('http://127.0.0.1:9222');
  const page = browser.contexts()[0].pages().find(p => p.url().includes('0e935f47-3f1e-4546-9972-431b328de86f'));
  if (page) {
    const topBatch = page.locator('.batch-container').first();
    const delBtn = topBatch.locator('button[aria-label="Xoá"], button:has-text("delete_forever")').first();
    console.log('Del btn count:', await delBtn.count());
    await delBtn.click();
    await new Promise(r => setTimeout(r, 600));

    // Check overlay
    const overlay = await page.$$eval('.cdk-overlay-pane, [role="dialog"]', els => els.map(e => e.innerText));
    console.log('Overlay text:', overlay);
  }
  await browser.close();
}

main().catch(console.error);
