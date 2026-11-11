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

  const uploadBtn = flowPage.locator('.cdk-overlay-pane button:has-text("Tải nội dung nghe nhìn lên")').first();
  console.log('Upload button exists:', await uploadBtn.count());

  // Check if file chooser is triggered on click
  const fileChooserPromise = flowPage.waitForEvent('filechooser', { timeout: 3000 }).catch(() => null);
  await uploadBtn.click();
  const fileChooser = await fileChooserPromise;
  console.log('File chooser triggered:', Boolean(fileChooser));

  await flowPage.keyboard.press('Escape');
  await flowPage.keyboard.press('Escape');
  await browser.close();
}

main().catch(console.error);
