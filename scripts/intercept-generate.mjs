import { chromium } from 'playwright-core';

async function main() {
  const browser = await chromium.connectOverCDP('http://127.0.0.1:9222');
  const page = browser.contexts()[0].pages().find(p => p.url().includes('0e935f47-3f1e-4546-9972-431b328de86f'));
  if (page) {
    page.on('request', req => {
      const u = req.url();
      if (u.includes('batchexecute')) {
        const postData = req.postData();
        console.log(`[BATCHEXECUTE REQ]:`, postData?.slice(0, 500));
      }
    });

    page.on('response', async res => {
      const u = res.url();
      if (u.includes('batchexecute')) {
        const text = await res.text().catch(() => '');
        console.log(`[BATCHEXECUTE RES ${res.status()}]:`, text.slice(0, 1000));
      }
    });

    console.log('Reloading page first...');
    await page.reload({ waitUntil: 'domcontentloaded' });
    await new Promise(r => setTimeout(r, 4000));

    // Try a manual prompt enter
    const promptBox = page.locator('flow-prompt-box [contenteditable="true"]').first();
    await promptBox.click();
    await page.keyboard.press('Control+A');
    await page.keyboard.type('A tranquil mountain lake in morning mist');
    await new Promise(r => setTimeout(r, 1000));

    const btn = page.locator('.generate-icon-button, button[aria-label*="Bắt đầu tạo" i]').first();
    console.log('Clicking generate icon button...');
    await btn.click();
    await new Promise(r => setTimeout(r, 10000));
  }
  await browser.close();
}

main().catch(console.error);
