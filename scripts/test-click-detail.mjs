import { chromium } from 'playwright-core';

async function main() {
  const browser = await chromium.connectOverCDP('http://127.0.0.1:9222');
  const context = browser.contexts()[0];
  const pages = context.pages();
  const p1 = pages.find(p => p.url().includes('0e935f47-3f1e-4546-9972-431b328de86f'));
  if (p1) {
    // Check if add menu open
    let popover = p1.locator('flow-add-menu-popover-content');
    if ((await popover.count()) === 0 || !(await popover.first().isVisible().catch(() => false))) {
      await p1.locator('.add-menu-trigger').first().click({ force: true });
      await popover.first().waitFor({ state: 'visible', timeout: 5000 });
    }

    const card = p1.locator('flow-add-menu-popover-content button.asset-item').filter({ hasText: 'mrkane-flow-reference.png' }).first();
    console.log('Card class before click:', await card.getAttribute('class'));

    // Check if detail button is already present
    const btnBefore = p1.locator('.detail-add-to-prompt-btn');
    console.log('Detail btn count before click:', await btnBefore.count());

    // Click card
    await card.click();
    await new Promise(r => setTimeout(r, 500));

    console.log('Card class after click:', await card.getAttribute('class'));
    console.log('Detail btn count after click:', await btnBefore.count());
    if (await btnBefore.count() > 0) {
      console.log('Detail btn visible:', await btnBefore.first().isVisible());
      console.log('Detail btn text:', await btnBefore.first().innerText());
      // Try clicking it via evaluate (dispatch click directly in DOM)
      const clicked = await p1.evaluate(() => {
        const btn = document.querySelector('.detail-add-to-prompt-btn');
        if (btn) {
          btn.click();
          return true;
        }
        return false;
      });
      console.log('DOM click returned:', clicked);
    }
    await new Promise(r => setTimeout(r, 1000));

    // Check chips
    const chips = await p1.$$eval('.chip-container', els => els.map(e => e.innerText));
    console.log('Prompt chips now:', chips);
  }
  await browser.close();
}

main().catch(console.error);
