import { chromium } from 'playwright-core';

async function main() {
  const browser = await chromium.connectOverCDP('http://127.0.0.1:9222');
  const context = browser.contexts()[0];
  const page = context.pages().find(p => p.url().includes('0e935f47-3f1e-4546-9972-431b328de86f'));
  if (page) {
    console.log('Cleaning up project 0e9...');
    await page.reload({ waitUntil: 'domcontentloaded' });
    await new Promise(r => setTimeout(r, 3000));

    // Delete any warning card if present
    const topBatch = page.locator('.batch-container').first();
    const text = await topBatch.innerText().catch(() => '');
    if (text.includes('Không thành công')) {
      console.log('Deleting top error card...');
      const delBtn = topBatch.locator('button:has-text("delete_forever"), button:has-text("delete"), button[aria-label*="Xoá" i]').first();
      if (await delBtn.count() > 0) {
        await delBtn.click();
        await new Promise(r => setTimeout(r, 600));
        const confBtn = page.locator('.cdk-overlay-pane button:has-text("Xoá"), .cdk-overlay-pane button:has-text("Xóa"), .cdk-overlay-pane button:has-text("Delete")').first();
        if (await confBtn.isVisible().catch(() => false)) {
          await confBtn.click();
          await new Promise(r => setTimeout(r, 1000));
          console.log('Deleted error card.');
        }
      }
    }
  }
  await browser.close();
}

main().catch(console.error);
