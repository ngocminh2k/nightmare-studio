import { chromium } from 'playwright-core';

async function testFreshTab() {
  const browser = await chromium.connectOverCDP('http://127.0.0.1:9222');
  const context = browser.contexts()[0];

  console.log('Opening a fresh tab for testing...');
  const newPage = await context.newPage();
  await newPage.goto('https://labs.google/fx/vi/tools/flow/project/0e935f47-3f1e-4546-9972-431b328de86f', { waitUntil: 'networkidle' });
  await new Promise(r => setTimeout(r, 4000));

  newPage.on('response', async res => {
    if (res.url().includes('batchexecute')) {
      const text = await res.text().catch(() => '');
      if (text.includes('ogiZ0b')) {
        console.log('[RESP ogiZ0b]:', text.slice(0, 300));
      }
    }
  });

  // Human-like mouse movement
  console.log('Simulating human mouse movements...');
  await newPage.mouse.move(100, 200);
  await new Promise(r => setTimeout(r, 200));
  await newPage.mouse.move(300, 400, { steps: 10 });
  await new Promise(r => setTimeout(r, 300));
  await newPage.mouse.move(500, 600, { steps: 10 });
  await new Promise(r => setTimeout(r, 500));

  // Focus prompt box
  const promptBox = newPage.locator('.ProseMirror[contenteditable="true"]').first();
  const box = await promptBox.boundingBox();
  if (box) {
    await newPage.mouse.move(box.x + box.width / 2, box.y + box.height / 2, { steps: 5 });
    await newPage.mouse.down();
    await new Promise(r => setTimeout(r, 80));
    await newPage.mouse.up();
  } else {
    await promptBox.click();
  }
  await new Promise(r => setTimeout(r, 400));

  await newPage.keyboard.press('Control+A');
  await newPage.keyboard.press('Backspace');
  await newPage.keyboard.type('A cinematic view of an old mysterious clock tower in heavy fog', { delay: 40 });
  await new Promise(r => setTimeout(r, 1200));

  // Move mouse to generate button
  const btn = newPage.locator('.generate-icon-button, button[aria-label*="Bắt đầu tạo" i]').first();
  const btnBox = await btn.boundingBox();
  if (btnBox) {
    await newPage.mouse.move(btnBox.x + btnBox.width / 2, btnBox.y + btnBox.height / 2, { steps: 8 });
    await new Promise(r => setTimeout(r, 600));
    console.log('Clicking generate with mouse click...');
    await newPage.mouse.down();
    await new Promise(r => setTimeout(r, 100));
    await newPage.mouse.up();
  } else {
    await btn.click();
  }

  await new Promise(r => setTimeout(r, 10000));

  const topBatch = newPage.locator('.batch-container').first();
  const text = await topBatch.innerText().catch(() => '');
  console.log('Top batch text:', text.slice(0, 200).replace(/\n+/g, ' '));

  await newPage.close();
  await browser.close();
}

testFreshTab().catch(console.error);
