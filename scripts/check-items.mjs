import { chromium } from 'playwright-core';

async function main() {
  const browser = await chromium.connectOverCDP('http://127.0.0.1:9222');
  const context = browser.contexts()[0];
  const pages = context.pages();
  const p1 = pages.find(p => p.url().includes('0e935f47-3f1e-4546-9972-431b328de86f'));
  if (p1) {
    const filename = 'mrkane-flow-reference.png';
    const card = p1.locator('.cdk-overlay-pane button.asset-item, .cdk-overlay-pane .asset-item')
      .filter({ hasText: filename })
      .first();
    console.log('Matching card count:', await card.count());
    if (await card.count() > 0) {
      console.log('Card text:', await card.innerText());
      await card.click();
      await new Promise(r => setTimeout(r, 600));

      const addBtn = p1.locator('.cdk-overlay-pane button.detail-add-to-prompt-btn, .cdk-overlay-pane button:has-text("Thêm vào câu lệnh")').first();
      console.log('Add button visible:', await addBtn.isVisible());
      if (await addBtn.isVisible()) {
        await addBtn.click();
        await new Promise(r => setTimeout(r, 1000));
        console.log('Successfully attached asset to prompt!');
      }
    }
  }
  await browser.close();
}

main().catch(console.error);
