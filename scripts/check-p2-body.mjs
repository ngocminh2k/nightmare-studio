import { chromium } from 'playwright-core';

async function main() {
  const browser = await chromium.connectOverCDP('http://127.0.0.1:9222');
  const context = browser.contexts()[0];
  const pages = context.pages();
  const p2 = pages.find(p => p.url().includes('6cb075cf-7b9e-4b65-b35c-24b363da057a'));
  if (p2) {
    console.log('Page 2 URL:', p2.url());
    const bodyText = await p2.evaluate(() => document.body.innerText.slice(0, 500));
    console.log('Body text snippet:\n', bodyText);
  }
  await browser.close();
}

main().catch(console.error);
