import { chromium } from 'playwright-core';

async function main() {
  const browser = await chromium.connectOverCDP('http://127.0.0.1:9222');
  const context = browser.contexts()[0];
  const pages = context.pages();
  const p2 = pages.find(p => p.url().includes('6cb075cf-7b9e-4b65-b35c-24b363da057a'));
  if (p2) {
    const promptBox = await p2.$('flow-prompt-box, textarea, [contenteditable="true"]');
    console.log('Prompt box present on p2?', !!promptBox);

    // Check buttons with icons like close, back, or canvas
    const navButtons = await p2.$$eval('button', els => els.map(b => ({
      text: b.innerText?.slice(0, 50).replace(/\n+/g, ' '),
      aria: b.getAttribute('aria-label')
    })));
    console.log('Buttons on p2:', navButtons.slice(0, 15));
  }
  await browser.close();
}

main().catch(console.error);
