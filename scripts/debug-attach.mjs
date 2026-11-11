import { chromium } from 'playwright-core';

async function main() {
  const browser = await chromium.connectOverCDP('http://127.0.0.1:9222');
  const context = browser.contexts()[0];
  const pages = context.pages();
  const p1 = pages.find(p => p.url().includes('0e935f47-3f1e-4546-9972-431b328de86f'));
  if (p1) {
    const overlays = await p1.$$eval('.cdk-overlay-pane, [role="dialog"], [role="menu"]', els => els.map(e => ({
      tag: e.tagName,
      class: e.className,
      text: e.innerText?.slice(0, 100)
    })));
    console.log('Overlays before click:', overlays);

    const addTrigger = p1.locator('.add-menu-trigger').first();
    await addTrigger.click({ force: true });
    await new Promise(r => setTimeout(r, 1000));

    const overlaysAfter = await p1.$$eval('.cdk-overlay-pane, [role="dialog"], [role="menu"]', els => els.map(e => ({
      tag: e.tagName,
      class: e.className,
      text: e.innerText?.slice(0, 100)
    })));
    console.log('Overlays after click:', overlaysAfter);
  }
  await browser.close();
}

main().catch(console.error);
