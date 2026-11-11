import { chromium } from 'playwright-core';

async function main() {
  const browser = await chromium.connectOverCDP('http://127.0.0.1:9222');
  const context = browser.contexts()[0];
  const pages = context.pages();
  const flowPage = pages.find(p => p.url().includes('flow.google.com'));
  if (!flowPage) {
    console.log('No Flow page found');
    await browser.close();
    return;
  }

  const parentInfo = await flowPage.evaluate(() => {
    const tb = document.querySelector('.batch-toolbar');
    if (!tb) return null;
    let curr = tb.parentElement;
    const hierarchy = [];
    while (curr && curr !== document.body && hierarchy.length < 6) {
      hierarchy.push({
        tag: curr.tagName,
        class: curr.className,
        id: curr.id,
        text: (curr.innerText || '').slice(0, 100),
      });
      curr = curr.parentElement;
    }
    return hierarchy;
  });

  console.log('Hierarchy:', JSON.stringify(parentInfo, null, 2));
  await browser.close();
}

main().catch(console.error);
