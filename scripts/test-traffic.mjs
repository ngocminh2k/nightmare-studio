import { chromium } from 'playwright-core';

async function testProject(projectUrl) {
  const browser = await chromium.connectOverCDP('http://127.0.0.1:9222');
  const page = browser.contexts()[0].pages().find(p => p.url().includes(projectUrl));
  if (!page) {
    console.log(`Page not found for ${projectUrl}`);
    await browser.close();
    return;
  }

  let errorInfo = null;
  const onRes = async res => {
    if (res.url().includes('batchexecute')) {
      const text = await res.text().catch(() => '');
      if (text.includes('ogiZ0b')) {
        console.log(`[RESP ogiZ0b]:`, text.slice(0, 300));
        if (text.includes('PUBLIC_ERROR')) {
          errorInfo = text;
        }
      }
    }
  };
  page.on('response', onRes);

  const promptBox = page.locator('flow-prompt-box [contenteditable="true"]').first();
  await promptBox.click();
  await page.keyboard.press('Control+A');
  await page.keyboard.type('A quiet autumn morning path');
  await new Promise(r => setTimeout(r, 1000));

  const btn = page.locator('.generate-icon-button, button[aria-label*="Bắt đầu tạo" i]').first();
  console.log(`Clicking generate in ${projectUrl}...`);
  await btn.click();
  await new Promise(r => setTimeout(r, 6000));

  page.off('response', onRes);
  await browser.close();
  return errorInfo;
}

async function main() {
  console.log('Testing project b8c...');
  await testProject('b8c98d11-92ce-430f-9114-f3f42c265cdf');
}

main().catch(console.error);
