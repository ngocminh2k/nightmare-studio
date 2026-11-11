import { chromium } from 'playwright-core';

async function main() {
  const browser = await chromium.connectOverCDP('http://127.0.0.1:9222');
  const context = browser.contexts()[0];
  const pages = context.pages();
  const p1 = pages.find(p => p.url().includes('0e935f47-3f1e-4546-9972-431b328de86f'));
  if (p1) {
    await p1.keyboard.press('Escape');
    await new Promise(r => setTimeout(r, 500));

    const addTrigger = p1.locator('.add-menu-trigger').first();
    console.log('Add trigger visible:', await addTrigger.isVisible());
    await addTrigger.click();
    await new Promise(r => setTimeout(r, 1000));

    const elements = await p1.$$eval('.cdk-overlay-pane *', els =>
      els.filter(e => e.innerText && e.innerText.trim().length > 0)
         .map(e => ({ tag: e.tagName, role: e.getAttribute('role'), aria: e.getAttribute('aria-label'), text: e.innerText.trim() }))
    );
    console.log('Overlay elements:', JSON.stringify(elements.slice(0, 10), null, 2));
  }
  await browser.close();
}

main().catch(console.error);
