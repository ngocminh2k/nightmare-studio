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

  const fileInputs = await flowPage.evaluate(() => {
    const inputs = Array.from(document.querySelectorAll('input[type="file"]'));
    return inputs.map((inp, idx) => ({
      idx,
      accept: inp.getAttribute('accept'),
      className: inp.className,
      parentTag: inp.parentElement?.tagName,
      parentClass: inp.parentElement?.className,
    }));
  });

  console.log('File Inputs on page:', JSON.stringify(fileInputs, null, 2));
  await browser.close();
}

main().catch(console.error);
