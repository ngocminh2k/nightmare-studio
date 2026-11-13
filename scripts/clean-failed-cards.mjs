import { chromium } from 'playwright-core';

async function main() {
  const browser = await chromium.connectOverCDP('http://127.0.0.1:9222');
  const context = browser.contexts()[0];
  const pages = context.pages().filter(p => p.url().includes('project'));

  for (const page of pages) {
    console.log(`Cleaning page: ${page.url().split('/').pop()}`);
    let deleted = 0;
    while (true) {
      const failedBatches = page.locator('.batch-container:has-text("Không thành công")');
      const count = await failedBatches.count().catch(() => 0);
      if (count === 0) break;

      const firstBatch = failedBatches.first();
      // Find the delete button inside the batch
      const delBtn = firstBatch.locator('button:has-text("delete_forever"), button:has-text("delete"), button[aria-label*="Xoá" i], button[aria-label*="Delete" i]').first();
      if (await delBtn.count() > 0) {
        await delBtn.click();
        await new Promise(r => setTimeout(r, 400));
        const confBtn = page.locator('.cdk-overlay-pane button:has-text("Xoá"), .cdk-overlay-pane button:has-text("Xóa"), .cdk-overlay-pane button:has-text("Delete")').first();
        if (await confBtn.isVisible().catch(() => false)) {
          await confBtn.click();
          await new Promise(r => setTimeout(r, 600));
          deleted++;
        } else {
          break;
        }
      } else {
        break;
      }
    }
    console.log(`Deleted ${deleted} failed cards from ${page.url().split('/').pop()}`);
  }

  await browser.close();
}

main().catch(console.error);
