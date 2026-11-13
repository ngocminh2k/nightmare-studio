import { chromium } from 'playwright-core';

async function testCardRetry() {
  const browser = await chromium.connectOverCDP('http://127.0.0.1:9222');
  const context = browser.contexts()[0];
  const page = context.pages().find(p => p.url().includes('0e935f47-3f1e-4546-9972-431b328de86f'));
  if (!page) {
    console.log('Page not found');
    await browser.close();
    return;
  }

  page.on('response', async res => {
    if (res.url().includes('batchexecute')) {
      const text = await res.text().catch(() => '');
      if (text.includes('ogiZ0b')) {
        console.log('[RETRY RPC]:', text.slice(0, 300));
      }
    }
  });

  const topBatch = page.locator('.batch-container').first();
  const retryBtn = topBatch.locator('button:has-text("refresh"), button:has-text("replay"), button[aria-label*="Thử lại" i], button mat-icon:has-text("refresh")').first();

  if (await retryBtn.count() > 0) {
    console.log('Clicking Retry button on failed card...');
    await retryBtn.click();
    await new Promise(r => setTimeout(r, 6000));
  } else {
    // List buttons inside topBatch
    const btns = await topBatch.$$eval('button', els => els.map(b => ({ text: b.innerText, label: b.getAttribute('aria-label') })));
    console.log('Buttons in topBatch:', btns);
  }

  await browser.close();
}

testCardRetry().catch(console.error);
