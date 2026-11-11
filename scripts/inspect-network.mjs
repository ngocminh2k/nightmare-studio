import { chromium } from 'playwright-core';

async function main() {
  const browser = await chromium.connectOverCDP('http://127.0.0.1:9222');
  const context = browser.contexts()[0];
  const page = context.pages().find(p => p.url().includes('0e935f47-3f1e-4546-9972-431b328de86f'));
  if (page) {
    console.log('Listening to network requests on 0e9...');

    page.on('request', req => {
      const u = req.url();
      if (u.includes('flow') || u.includes('generate') || u.includes('batch') || u.includes('aisandbox')) {
        console.log(`[REQ] ${req.method()} ${u.slice(0, 120)}`);
      }
    });

    page.on('response', async res => {
      const u = res.url();
      if (u.includes('flow') || u.includes('generate') || u.includes('batch') || u.includes('aisandbox')) {
        console.log(`[RES] ${res.status()} ${u.slice(0, 120)}`);
        try {
          const body = await res.text();
          console.log(`[RES BODY]`, body.slice(0, 300));
        } catch {}
      }
    });

    // Delete the top error card first!
    const delBtn = page.locator('.batch-container button:has-text("delete_forever"), .batch-container button[aria-label*="Xoá" i]').first();
    if (await delBtn.count() > 0) {
      console.log('Deleting top error card...');
      await delBtn.click();
      await new Promise(r => setTimeout(r, 600));
      const confBtn = page.locator('.cdk-overlay-pane button:has-text("Xoá"), .cdk-overlay-pane button:has-text("Xóa"), .cdk-overlay-pane button:has-text("Delete")').first();
      if (await confBtn.isVisible().catch(() => false)) {
        await confBtn.click();
        await new Promise(r => setTimeout(r, 1000));
        console.log('Deleted error card.');
      }
    }

    // Now try clicking generate
    const btn = page.locator('button.create-btn, button:has-text("arrow_forward"), button:has-text("Tạo")').first();
    console.log('Clicking generate...');
    await btn.click();
    await new Promise(r => setTimeout(r, 8000));
  }
  await browser.close();
}

main().catch(console.error);
