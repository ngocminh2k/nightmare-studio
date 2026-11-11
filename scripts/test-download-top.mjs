import { chromium } from 'playwright-core';
import { existsSync, statSync } from 'fs';

async function main() {
  const browser = await chromium.connectOverCDP('http://127.0.0.1:9222');
  const context = browser.contexts()[0];
  const pages = context.pages();
  const flowPage = pages.find(p => p.url().includes('flow.google.com'));
  if (!flowPage) {
    console.log('No Flow page found');
    await browser.close();
    return;
  }

  // Find the top download button
  const topDlBtn = flowPage.locator('.batch-toolbar button[aria-label="Tải xuống hàng loạt"]').first();
  console.log('Top button exists:', await topDlBtn.count());

  try {
    const downloadPromise = flowPage.waitForEvent('download', { timeout: 15000 });
    console.log('Clicking top download button...');
    await topDlBtn.click();
    console.log('Waiting for download event...');
    const download = await downloadPromise;
    console.log('Download suggested filename:', download.suggestedFilename());
    const dest = 'data/test-top-download.bin';
    await download.saveAs(dest);
    console.log('Saved to', dest, 'size:', statSync(dest).size);
  } catch (err) {
    console.log('Download attempt error:', err.message);
  }

  await browser.close();
}

main().catch(console.error);
