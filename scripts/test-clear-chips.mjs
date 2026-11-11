import { chromium } from 'playwright-core';

async function main() {
  const browser = await chromium.connectOverCDP('http://127.0.0.1:9222');
  const context = browser.contexts()[0];
  const pages = context.pages();
  const p1 = pages.find(p => p.url().includes('0e935f47-3f1e-4546-9972-431b328de86f'));
  if (p1) {
    const cancelChips = p1.locator('.chip-container:has-text("cancel"), flow-prompt-box button:has-text("cancel"), flow-prompt-box mat-icon:has-text("cancel")');
    let count = await cancelChips.count();
    console.log('Cancelling', count, 'chips...');
    while (count > 0) {
      await cancelChips.first().click().catch(() => {});
      await new Promise(r => setTimeout(r, 200));
      const newCount = await cancelChips.count();
      if (newCount === count) break; // prevent infinite loop
      count = newCount;
    }
    console.log('Remaining cancel chips:', await cancelChips.count());
  }
  await browser.close();
}

main().catch(console.error);
