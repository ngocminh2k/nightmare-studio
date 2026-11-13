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

  // Click cancel on the start frame slot to reset it
  const cancelBtn = flowPage.locator('.frame-trigger button:has-text("cancel"), .frame-trigger button[aria-label*="Xoá" i], .frame-trigger mat-icon:has-text("cancel")').first();
  console.log('Cancel button count:', await cancelBtn.count());
  if (await cancelBtn.count()) {
    await cancelBtn.click();
    await new Promise(r => setTimeout(r, 500));
    console.log('Slot reset text:', (await flowPage.locator('.frame-trigger').first().innerText()).trim());
  }

  await browser.close();
}

main().catch(console.error);
