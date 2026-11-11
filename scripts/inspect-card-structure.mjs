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

  const cardInfo = await flowPage.evaluate(() => {
    const toolbars = Array.from(document.querySelectorAll('.batch-toolbar'));
    return toolbars.slice(0, 3).map((tb, i) => {
      const container = tb.closest('div[role="listitem"], .asset-card, .card, div[class*="item"], div[class*="batch"]') || tb.parentElement;
      return {
        toolbarIndex: i,
        toolbarHTML: tb.outerHTML.slice(0, 300),
        containerClass: container?.className,
        containerHTML: container?.outerHTML.slice(0, 500),
      };
    });
  });

  console.log('Top Card Info:', JSON.stringify(cardInfo, null, 2));
  await browser.close();
}

main().catch(console.error);
