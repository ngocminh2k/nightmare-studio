import { chromium } from 'playwright-core';

async function main() {
  const browser = await chromium.connectOverCDP('http://127.0.0.1:9222');
  const context = browser.contexts()[0];
  const pages = context.pages();
  const p1 = pages.find(p => p.url().includes('0e935f47-3f1e-4546-9972-431b328de86f'));
  if (p1) {
    // 1. Open add menu
    let popover = p1.locator('flow-add-menu-popover-content');
    if ((await popover.count()) === 0 || !(await popover.first().isVisible().catch(() => false))) {
      console.log('Opening add menu...');
      const trigger = p1.locator('.add-menu-trigger').first();
      await trigger.click({ force: true });
      await popover.first().waitFor({ state: 'visible', timeout: 5000 });
    }

    // 2. Click asset-item for mrkane-flow-reference.png
    console.log('Locating mrkane reference asset...');
    const card = p1.locator('flow-add-menu-popover-content button.asset-item').filter({ hasText: 'mrkane-flow-reference.png' }).first();
    await card.waitFor({ state: 'visible', timeout: 5000 });
    await card.click();
    console.log('Clicked asset card.');

    // 3. Wait for and click detail-add-to-prompt-btn
    const addBtn = p1.locator('flow-add-menu-popover-content button.detail-add-to-prompt-btn').first();
    await addBtn.waitFor({ state: 'visible', timeout: 5000 });
    await addBtn.click();
    console.log('Clicked detail-add-to-prompt-btn.');

    await p1.keyboard.press('Escape').catch(() => {});
    await new Promise(r => setTimeout(r, 600));

    // 4. Verify chip in prompt box
    const cancelChips = p1.locator('.chip-container:has-text("cancel"), flow-prompt-box button:has-text("cancel")');
    console.log('Attached cancel chips count:', await cancelChips.count());
  }
  await browser.close();
}

main().catch(console.error);
