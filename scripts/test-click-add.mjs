import { chromium } from 'playwright-core';

async function main() {
  const browser = await chromium.connectOverCDP('http://127.0.0.1:9222');
  const context = browser.contexts()[0];
  const pages = context.pages();
  const p1 = pages.find(p => p.url().includes('0e935f47-3f1e-4546-9972-431b328de86f'));
  if (p1) {
    // 1. Check if add menu is open
    let popover = await p1.$('flow-add-menu-popover-content');
    if (!popover) {
      console.log('Opening add menu...');
      const trigger = p1.locator('.add-menu-trigger').first();
      await trigger.click({ force: true });
      await p1.waitForSelector('flow-add-menu-popover-content', { state: 'visible', timeout: 5000 });
    }

    // 2. Click asset-item matching mrkane-flow-reference.png
    console.log('Clicking mrkane reference card...');
    const card = p1.locator('flow-add-menu-popover-content button.asset-item').filter({ hasText: 'mrkane-flow-reference.png' }).first();
    await card.click();
    await new Promise(r => setTimeout(r, 600));

    // 3. Click detail-add-to-prompt-btn
    console.log('Clicking detail-add-to-prompt-btn...');
    const addBtn = p1.locator('flow-add-menu-popover-content button.detail-add-to-prompt-btn').first();
    await addBtn.click();
    await new Promise(r => setTimeout(r, 1000));

    // 4. Check prompt box to see what is attached!
    const promptAttachments = await p1.evaluate(() => {
      // Find chips or attached images in prompt area
      const chips = Array.from(document.querySelectorAll('.prompt-input-container [role="button"], .prompt-box-wrapper img, .prompt-box-wrapper .mat-mdc-chip, flow-image-chip, [class*="chip"], [class*="attachment"]')).map(el => ({
        tag: el.tagName,
        class: el.className,
        text: el.innerText?.slice(0, 50).replace(/\n+/g, ' ')
      }));
      return chips;
    });
    console.log('Prompt attachments:', promptAttachments);
  }
  await browser.close();
}

main().catch(console.error);
