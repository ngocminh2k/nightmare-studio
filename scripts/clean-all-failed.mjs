import { chromium } from 'playwright-core';

async function main() {
  const browser = await chromium.connectOverCDP('http://127.0.0.1:9222');
  const context = browser.contexts()[0];
  const pages = context.pages().filter(p => p.url().includes('project'));

  for (const page of pages) {
    const slug = page.url().split('/').pop();
    let count = 0;
    while (true) {
      const failed = page.locator('.batch-container:has-text("Không thành công")');
      if (await failed.count() === 0) break;
      const delBtn = failed.first().locator('button[aria-label="Xoá"], button:has-text("delete_forever")').first();
      if (await delBtn.count() > 0) {
        await delBtn.click();
        await new Promise(r => setTimeout(r, 600));
        count++;
      } else {
        break;
      }
    }
    console.log(`Cleaned ${count} failed cards from ${slug}`);
  }

  await browser.close();
}

main().catch(console.error);
