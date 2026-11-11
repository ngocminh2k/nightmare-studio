import { chromium } from 'playwright-core';

async function main() {
  const browser = await chromium.connectOverCDP('http://127.0.0.1:9222');
  const context = browser.contexts()[0];
  const pages = context.pages();
  const p2 = pages.find(p => p.url().includes('6cb075cf-7b9e-4b65-b35c-24b363da057a'));
  if (p2) {
    const text = await p2.evaluate(() => {
      // Find cards with warning or delete buttons
      const cards = Array.from(document.querySelectorAll('flow-batch-card, [data-card-open], .batch-card')).map(c => ({
        tag: c.tagName,
        text: (c.innerText || '').slice(0, 150).replace(/\n+/g, ' ')
      }));
      return cards;
    });
    console.log('Cards in project 2:', text);
  }
  await browser.close();
}

main().catch(console.error);
