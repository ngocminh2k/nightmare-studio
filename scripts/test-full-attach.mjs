import { chromium } from 'playwright-core';

async function main() {
  const browser = await chromium.connectOverCDP('http://127.0.0.1:9222');
  const context = browser.contexts()[0];
  const pages = context.pages();
  const p1 = pages.find(p => p.url().includes('0e935f47-3f1e-4546-9972-431b328de86f'));
  if (p1) {
    // Step 1: Clear existing cancel chips
    console.log('--- Step 1: Clearing existing cancel chips ---');
    const cancelChips = p1.locator('.chip-container:has-text("cancel"), flow-prompt-box button:has-text("cancel")');
    while (await cancelChips.count() > 0) {
      await cancelChips.first().click().catch(() => {});
      await new Promise(r => setTimeout(r, 200));
    }
    const chipsAfterClear = await p1.locator('.chip-container:has-text("cancel")').count();
    console.log('Cancel chips after clear:', chipsAfterClear);

    // Step 2: Open add menu
    console.log('--- Step 2: Opening add menu ---');
    const trigger = p1.locator('.add-menu-trigger').first();
    await trigger.click({ force: true });
    await p1.waitForSelector('flow-add-menu-popover-content', { state: 'visible', timeout: 5000 });
    console.log('Add menu popover is visible.');

    // Step 3 & 4: Find and select mrkane asset item
    console.log('--- Step 3: Selecting mrkane asset item ---');
    const mrkaneCard = p1.locator('flow-add-menu-popover-content button.asset-item').filter({ hasText: 'mrkane-flow-reference.png' }).first();
    await mrkaneCard.waitFor({ state: 'visible', timeout: 5000 });

    // Check if active
    const isActive = await mrkaneCard.evaluate(el => el.classList.contains('asset-item-active'));
    console.log('Asset card is active before click:', isActive);
    if (!isActive) {
      await mrkaneCard.click();
      await new Promise(r => setTimeout(r, 500));
    }

    // Step 5 & 6: Click detail-add-to-prompt-btn
    console.log('--- Step 4: Clicking detail-add-to-prompt-btn ---');
    const addBtn = p1.locator('.detail-add-to-prompt-btn').first();
    await addBtn.waitFor({ state: 'visible', timeout: 5000 });
    // Click via DOM to prevent race condition when popover closes
    await addBtn.evaluate(el => el.click());
    console.log('Add button clicked.');

    // Step 7: Wait for UI to settle
    await new Promise(r => setTimeout(r, 1000));

    // Step 8: Verify chip attached
    const finalChips = await p1.locator('.chip-container:has-text("cancel")').count();
    console.log('--- Step 5: Final cancel chips count ---:', finalChips);
  }
  await browser.close();
}

main().catch(console.error);
