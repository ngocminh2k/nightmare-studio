import { chromium } from 'playwright-core';

async function testSingleGen() {
  const browser = await chromium.connectOverCDP('http://127.0.0.1:9222');
  const context = browser.contexts()[0];
  const page = context.pages().find(p => p.url().includes('0e935f47-3f1e-4546-9972-431b328de86f'));
  if (!page) {
    console.log('Page not found');
    await browser.close();
    return;
  }

  let rpcResult = null;
  const onRes = async res => {
    if (res.url().includes('batchexecute')) {
      const text = await res.text().catch(() => '');
      if (text.includes('ogiZ0b')) {
        rpcResult = text;
        console.log('[GEN RPC RESULT]:', text.slice(0, 300));
      }
    }
  };
  page.on('response', onRes);

  const promptBox = page.locator('.ProseMirror[contenteditable="true"]').first();
  await promptBox.focus();
  await page.keyboard.press('Control+A');
  await page.keyboard.press('Backspace');
  await page.keyboard.insertText('A quiet dark autumn forest in deep fog, 2.5D comic style');
  await new Promise(r => setTimeout(r, 1500));

  const btn = page.locator('.generate-icon-button, button[aria-label*="Bắt đầu tạo" i]').first();
  console.log('Clicking generate...');
  await btn.click();
  await new Promise(r => setTimeout(r, 8000));

  page.off('response', onRes);
  await browser.close();

  if (rpcResult && rpcResult.includes('PUBLIC_ERROR_UNUSUAL_ACTIVITY_TOO_MUCH_TRAFFIC')) {
    console.log('Still in cooldown.');
  } else if (rpcResult) {
    console.log('ACCEPTED / PROCESSING!');
  }
}

testSingleGen().catch(console.error);
