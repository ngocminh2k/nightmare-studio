import { chromium } from 'playwright-core';
import { basename } from 'node:path';

async function main() {
  const browser = await chromium.connectOverCDP('http://127.0.0.1:9222');
  const context = browser.contexts()[0];
  const pages = context.pages();
  const p1 = pages.find(p => p.url().includes('0e935f47-3f1e-4546-9972-431b328de86f'));
  if (p1) {
    const candidateCards = p1.locator(
      '.cdk-overlay-pane button.asset-item, .cdk-overlay-pane .asset-item'
    );
    const targetCard = candidateCards.filter({ hasText: 'mrkane-flow-reference.png' }).first();
    await targetCard.click();
    await new Promise(r => setTimeout(r, 1000));

    // Inspect all buttons currently in the document!
    const buttons = await p1.$$eval('button', els =>
      els.filter(b => b.offsetWidth || b.offsetHeight)
         .map(b => ({
           text: b.innerText.slice(0, 50).replace(/\n+/g, ' '),
           aria: b.getAttribute('aria-label'),
           class: b.className
         }))
    );
    console.log('Visible buttons in document:\n', JSON.stringify(buttons.filter(b => b.text.includes('Thêm') || b.text.includes('Add') || b.class.includes('detail') || b.class.includes('prompt')), null, 2));
  }
  await browser.close();
}

main().catch(console.error);
