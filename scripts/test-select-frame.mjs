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

  const startBtn = flowPage.locator('button.empty-chip:has-text("Bắt đầu"), .frame-trigger button').first();
  await startBtn.click();
  await new Promise(r => setTimeout(r, 600));

  const scene1Btn = flowPage.locator('.cdk-overlay-pane button:has-text("scene-001.png")').first();
  console.log('scene-001.png card count:', await scene1Btn.count());
  if (await scene1Btn.count()) {
    console.log('Clicking scene-001.png card...');
    await scene1Btn.click();
    await new Promise(r => setTimeout(r, 600));

    // Check if there is an Add button or if overlay closed
    const overlayOpen = await flowPage.locator('.cdk-overlay-pane').count();
    console.log('Overlay still open:', overlayOpen > 0);

    const startChip = await flowPage.locator('.frame-trigger').first().innerText();
    console.log('Start frame slot text now:', startChip.replace(/\s+/g, ' ').trim());
  }

  await browser.close();
}

main().catch(console.error);
