import { chromium } from 'playwright-core';
import { isFlowPage } from './flow-url.mjs';

async function main() {
  const browser = await chromium.connectOverCDP('http://127.0.0.1:9222');
  const context = browser.contexts()[0];
  const pages = context.pages();
  const flowPage = pages.find(p => isFlowPage(p.url()));
  if (!flowPage) {
    console.log('No Flow page found');
    await browser.close();
    return;
  }

  const startBtnInfo = await flowPage.evaluate(() => {
    const btn = Array.from(document.querySelectorAll('button')).find(b => b.innerText.includes('Bắt đầu'));
    return {
      outerHTML: btn?.outerHTML.slice(0, 300),
      parentOuter: btn?.parentElement?.outerHTML.slice(0, 400),
    };
  });

  console.log('Start button:', JSON.stringify(startBtnInfo, null, 2));
  await browser.close();
}

main().catch(console.error);
