import { chromium } from 'playwright-core';

async function main() {
  const browser = await chromium.connectOverCDP('http://127.0.0.1:9222');
  const context = browser.contexts()[0];
  const pages = context.pages();
  const p1 = pages.find(p => p.url().includes('0e935f47-3f1e-4546-9972-431b328de86f'));
  if (p1) {
    const chips = p1.locator('.chip-container, button:has-text("cancel"), mat-icon:has-text("cancel")');
    const count = await chips.count();
    console.log('Total chip count:', count);
    for (let i = 0; i < count; i++) {
      const text = await chips.nth(i).innerText().catch(() => '');
      const isVis = await chips.nth(i).isVisible().catch(() => false);
      console.log(`Chip ${i}: visible=${isVis}, text=${JSON.stringify(text)}`);
    }
  }
  await browser.close();
}

main().catch(console.error);
