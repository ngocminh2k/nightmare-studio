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
  console.log('Clicking start button...');
  await startBtn.click();
  await new Promise(r => setTimeout(r, 1000));

  const overlayInfo = await flowPage.evaluate(() => {
    const pane = document.querySelector('.cdk-overlay-pane');
    if (!pane) return null;
    const btns = Array.from(pane.querySelectorAll('button')).map(b => (b.innerText || b.getAttribute('aria-label') || '').trim());
    const fileInputs = Array.from(pane.querySelectorAll('input[type="file"]')).map(i => i.outerHTML.slice(0, 100));
    return {
      buttons: btns.slice(0, 15),
      fileInputs,
    };
  });

  console.log('Overlay info after click:', JSON.stringify(overlayInfo, null, 2));

  // Close by pressing Escape
  await flowPage.keyboard.press('Escape');
  await browser.close();
}

main().catch(console.error);
