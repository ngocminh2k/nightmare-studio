import { chromium } from 'playwright';
import { isFlowPage } from './flow-url.mjs';

async function main() {
  const browser = await chromium.connectOverCDP('http://127.0.0.1:9222');
  const context = browser.contexts()[0] || (await browser.newContext());
  const page = context.pages().find((p) => isFlowPage(p.url())) || context.pages()[0];
  const count = await page.locator('.batch-container').count();
  for (let i = 0; i < count; i++) {
    const topBatch = page.locator('.batch-container').first();
    const text = await topBatch.innerText().catch(() => '');
    if (text.includes('Không thành công')) {
      const delBtn = topBatch.locator('button:has-text("delete_forever")').first();
      if ((await delBtn.count()) > 0) {
        await delBtn.click();
        await new Promise((r) => setTimeout(r, 600));
        const confirmBtn = page.locator('.cdk-overlay-pane button:has-text("Xoá"), .cdk-overlay-pane button:has-text("Xóa"), .cdk-overlay-pane button:has-text("Delete")').first();
        if (await confirmBtn.isVisible().catch(() => false)) {
          await confirmBtn.click();
          await new Promise((r) => setTimeout(r, 800));
        }
        console.log('Permanently deleted 1 failed batch');
      } else {
        break;
      }
    } else {
      break;
    }
  }
  await browser.close();
}

main().catch(console.error);
