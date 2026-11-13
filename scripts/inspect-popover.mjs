import { chromium } from 'playwright-core';

async function main() {
  const browser = await chromium.connectOverCDP('http://127.0.0.1:9222');
  const context = browser.contexts()[0];
  const pages = context.pages();
  const p1 = pages.find(p => p.url().includes('0e935f47-3f1e-4546-9972-431b328de86f'));
  if (p1) {
    // If not open, click trigger
    const openPane = await p1.$('.cdk-overlay-pane flow-add-menu-popover-content');
    if (!openPane) {
      const addTrigger = p1.locator('.add-menu-trigger').first();
      await addTrigger.click({ force: true });
      await new Promise(r => setTimeout(r, 1000));
    }

    const info = await p1.evaluate(() => {
      const popover = document.querySelector('flow-add-menu-popover-content') || document.querySelector('.cdk-overlay-pane');
      if (!popover) return 'No popover found';

      const buttons = Array.from(popover.querySelectorAll('button, .asset-item, [role="button"]')).map(b => ({
        tag: b.tagName,
        class: b.className,
        text: b.innerText?.slice(0, 80).replace(/\n+/g, ' '),
        aria: b.getAttribute('aria-label'),
        title: b.getAttribute('title')
      }));
      return { buttons };
    });
    console.log(JSON.stringify(info, null, 2));
  }
  await browser.close();
}

main().catch(console.error);
