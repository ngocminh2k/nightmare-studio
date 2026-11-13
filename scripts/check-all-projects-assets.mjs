import { chromium } from 'playwright-core';

const PROJECTS = [
  '0e935f47-3f1e-4546-9972-431b328de86f',
  'b8c98d11-92ce-430f-9114-f3f42c265cdf',
  '6cb075cf-7b9e-4b65-b35c-24b363da057a'
];

async function main() {
  const browser = await chromium.connectOverCDP('http://127.0.0.1:9222');
  const context = browser.contexts()[0];
  const pages = context.pages();

  for (const proj of PROJECTS) {
    console.log(`\n=== Checking project ${proj} ===`);
    let page = pages.find(p => p.url().includes(proj));
    if (!page) {
      console.log('Opening new page for project...');
      page = await context.newPage();
      await page.goto(`https://labs.google/fx/vi/tools/flow/project/${proj}`, { waitUntil: 'domcontentloaded' });
      await new Promise(r => setTimeout(r, 3000));
    }

    // Open add menu
    let popover = page.locator('flow-add-menu-popover-content');
    if ((await popover.count()) === 0 || !(await popover.first().isVisible().catch(() => false))) {
      const trigger = page.locator('.add-menu-trigger').first();
      await trigger.click({ force: true });
      await popover.first().waitFor({ state: 'visible', timeout: 5000 }).catch(() => {});
    }

    // Check mrkane asset
    const mrkaneCard = page.locator('flow-add-menu-popover-content button.asset-item').filter({ hasText: 'mrkane-flow-reference.png' });
    const count = await mrkaneCard.count().catch(() => 0);
    console.log(`mrkane reference asset count in ${proj}:`, count);
    await page.keyboard.press('Escape').catch(() => {});
  }
  await browser.close();
}

main().catch(console.error);
