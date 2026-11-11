import { chromium } from 'playwright-core';

async function testWait() {
  console.log('Sleeping 45 seconds to let Google Flow rate limit cooldown...');
  await new Promise(r => setTimeout(r, 45000));

  const browser = await chromium.connectOverCDP('http://127.0.0.1:9222');
  const page = browser.contexts()[0].pages().find(p => p.url().includes('0e935f47-3f1e-4546-9972-431b328de86f'));
  if (!page) {
    console.log('Page not found');
    await browser.close();
    return;
  }

  page.on('response', async res => {
    if (res.url().includes('batchexecute')) {
      const text = await res.text().catch(() => '');
      if (text.includes('ogiZ0b')) {
        console.log('[RESP ogiZ0b]:', text.slice(0, 300));
      }
    }
  });

  const promptBox = page.locator('.ProseMirror[contenteditable="true"]').first();
  await promptBox.focus();
  await page.keyboard.press('Control+A');
  await page.keyboard.press('Backspace');
  await page.keyboard.insertText('A quiet dark alley at midnight');
  await new Promise(r => setTimeout(r, 1000));

  const btn = page.locator('.generate-icon-button, button[aria-label*="Bắt đầu tạo" i]').first();
  console.log('Clicking generate...');
  await btn.click();
  await new Promise(r => setTimeout(r, 8000));

  const topBatch = page.locator('.batch-container').first();
  const text = await topBatch.innerText().catch(() => '');
  console.log('Top batch text:', text.slice(0, 200).replace(/\n+/g, ' '));

  await browser.close();
}

testWait().catch(console.error);
