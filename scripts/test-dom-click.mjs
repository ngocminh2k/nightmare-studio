import { chromium } from 'playwright-core';

async function main() {
  const browser = await chromium.connectOverCDP('http://127.0.0.1:9222');
  const context = browser.contexts()[0];
  const pages = context.pages();
  const p1 = pages.find(p => p.url().includes('0e935f47-3f1e-4546-9972-431b328de86f'));
  if (p1) {
    const res = await p1.evaluate(() => {
      // 1. Check if add menu is open
      const popover = document.querySelector('flow-add-menu-popover-content');
      if (!popover) return { error: 'Popover not open' };

      // 2. Find asset item for mrkane
      const items = Array.from(popover.querySelectorAll('button.asset-item'));
      const mrkaneItem = items.find(el => el.textContent.includes('mrkane-flow-reference.png'));
      if (!mrkaneItem) return { error: 'Asset item not found' };

      // Check if it's already active
      const isActive = mrkaneItem.classList.contains('asset-item-active');
      if (!isActive) {
        mrkaneItem.click();
      }

      // Check detail add button
      const addBtn = popover.querySelector('.detail-add-to-prompt-btn') || document.querySelector('.detail-add-to-prompt-btn');
      if (!addBtn) {
        return { isActive, clickedItem: !isActive, error: 'Add button not found immediately' };
      }

      addBtn.click();
      return { success: true, isActive, clickedItem: !isActive, addBtnText: addBtn.textContent.trim() };
    });
    console.log('Evaluate result:', res);

    await new Promise(r => setTimeout(r, 1000));
    const chips = await p1.$$eval('.chip-container', els => els.map(e => e.innerText));
    console.log('Prompt chips now:', chips);
  }
  await browser.close();
}

main().catch(console.error);
