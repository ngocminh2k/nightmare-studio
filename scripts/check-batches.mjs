import { chromium } from 'playwright-core';

async function main() {
  const browser = await chromium.connectOverCDP('http://127.0.0.1:9222');
  const context = browser.contexts()[0];
  const pages = context.pages();
  const p3 = pages.find(p => p.url().includes('6cb075cf-7b9e-4b65-b35c-24b363da057a'));
  if (p3) {
    const batches = await p3.$$eval('.batch-container', els => els.map(e => e.innerText.slice(0, 150)));
    console.log('Project 3 total batches:', batches.length);
    console.log('First 3 batches:', batches.slice(0, 3));
  }
  await browser.close();
}

main().catch(console.error);
