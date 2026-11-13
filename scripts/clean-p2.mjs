import { chromium } from 'playwright-core';

async function main() {
  const browser = await chromium.connectOverCDP('http://127.0.0.1:9222');
  const context = browser.contexts()[0];
  const pages = context.pages();
  const p2 = pages.find(p => p.url().includes('6cb075cf-7b9e-4b65-b35c-24b363da057a'));
  if (p2) {
    // Check for any cards or warning banners
    const warnings = await p2.$$eval('[class*="warning"], [class*="error"], .flow-banner, flow-batch-card', els => els.map(e => ({
      class: e.className,
      text: e.innerText?.slice(0, 100).replace(/\n+/g, ' ')
    })));
    console.log('Warnings/cards on p2:', warnings);

    // Let's reload p2 to clear any transient UI state
    console.log('Reloading p2...');
    await p2.reload({ waitUntil: 'domcontentloaded' });
    await new Promise(r => setTimeout(r, 3000));
    console.log('P2 reloaded successfully.');
  }
  await browser.close();
}

main().catch(console.error);
