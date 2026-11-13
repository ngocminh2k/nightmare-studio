import { chromium } from 'playwright-core';

async function testGenOnNewProject() {
  const browser = await chromium.connectOverCDP('http://127.0.0.1:9222');
  const context = browser.contexts()[0];
  const page = await context.newPage();
  await page.goto('https://flow.google.com/project/1d9f740b-fbad-45c2-8086-0b1c793b1112', { waitUntil: 'networkidle' });
  await new Promise(r => setTimeout(r, 4000));

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
  await page.keyboard.insertText('A misty mountain lake at dawn, cinematic 8k');
  await new Promise(r => setTimeout(r, 1000));

  const btn = page.locator('.generate-icon-button, button[aria-label*="Bắt đầu tạo" i]').first();
  console.log('Clicking generate on new project...');
  await btn.click();
  await new Promise(r => setTimeout(r, 8000));

  const topBatch = page.locator('.batch-container').first();
  const text = await topBatch.innerText().catch(() => '');
  console.log('Top batch text:', text.slice(0, 200).replace(/\n+/g, ' '));

  await page.close();
  await browser.close();
}

testGenOnNewProject().catch(console.error);
