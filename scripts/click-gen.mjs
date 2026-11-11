import { chromium } from 'playwright-core';

async function main() {
  const browser = await chromium.connectOverCDP('http://127.0.0.1:9222');
  const context = browser.contexts()[0];
  const pages = context.pages();
  const p1 = pages.find(p => p.url().includes('0e935f47-3f1e-4546-9972-431b328de86f'));
  if (p1) {
    const genBtn = p1.locator('.generate-icon-button, button[aria-label*="Bắt đầu tạo" i]').first();
    console.log('Generate button enabled:', !(await genBtn.isDisabled()));
    if (!(await genBtn.isDisabled())) {
      await genBtn.click();
      console.log('Clicked generate!');
    }
  }
  await browser.close();
}

main().catch(console.error);
