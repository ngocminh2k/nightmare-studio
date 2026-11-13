import { chromium } from 'playwright-core';

async function main() {
  const browser = await chromium.connectOverCDP('http://127.0.0.1:9222');
  const context = browser.contexts()[0];
  const pages = context.pages();
  const p3 = pages.find(p => p.url().includes('6cb075cf-7b9e-4b65-b35c-24b363da057a'));
  if (p3) {
    const batches = await p3.$$eval('.batch-container', els => els.map((e, idx) => ({
      idx,
      text: e.innerText.replace(/\n+/g, ' ').slice(0, 120),
      hasImg: !!e.querySelector('img'),
      imgSrc: e.querySelector('img')?.src?.slice(0, 80)
    })));
    console.log(JSON.stringify(batches, null, 2));
  }
  await browser.close();
}

main().catch(console.error);
