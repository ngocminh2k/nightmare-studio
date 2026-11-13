import { chromium } from 'playwright-core';

// Bezier curve mouse movement to look completely human
async function humanMouseMove(page, targetX, targetY) {
  // Get current position or start from somewhere plausible
  const currentPos = await page.evaluate(() => {
    return { x: window.innerWidth / 2, y: window.innerHeight / 2 };
  });

  const startX = currentPos.x;
  const startY = currentPos.y;
  const cpX = (startX + targetX) / 2 + (Math.random() - 0.5) * 100;
  const cpY = (startY + targetY) / 2 + (Math.random() - 0.5) * 100;

  const steps = 25;
  for (let i = 1; i <= steps; i++) {
    const t = i / steps;
    const x = (1 - t) * (1 - t) * startX + 2 * (1 - t) * t * cpX + t * t * targetX;
    const y = (1 - t) * (1 - t) * startY + 2 * (1 - t) * t * cpY + t * t * targetY;
    await page.mouse.move(x, y);
    await new Promise(r => setTimeout(r, 10 + Math.random() * 15));
  }
}

async function testHumanFlow() {
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
        console.log('[PROBE RPC]:', text.slice(0, 300));
      }
    }
  };
  page.on('response', onRes);

  console.log('Starting human-like interaction...');
  // 1. Move mouse around canvas
  await humanMouseMove(page, 400, 300);
  await new Promise(r => setTimeout(r, 300));
  await humanMouseMove(page, 550, 500);
  await new Promise(r => setTimeout(r, 400));

  // 2. Move to prompt box
  const promptBox = page.locator('.ProseMirror[contenteditable="true"]').first();
  const box = await promptBox.boundingBox();
  if (box) {
    await humanMouseMove(page, box.x + box.width / 3, box.y + box.height / 2);
    await new Promise(r => setTimeout(r, 200));
    await page.mouse.down();
    await new Promise(r => setTimeout(r, 90));
    await page.mouse.up();
  } else {
    await promptBox.click();
  }
  await new Promise(r => setTimeout(r, 500));

  await page.keyboard.press('Control+A');
  await new Promise(r => setTimeout(r, 100));
  await page.keyboard.press('Backspace');
  await new Promise(r => setTimeout(r, 300));

  // Type at human typing speed (30-70ms per char)
  const prompt = 'A mysterious lantern glowing in the dark damp autumn woods';
  for (const char of prompt) {
    await page.keyboard.type(char);
    await new Promise(r => setTimeout(r, 25 + Math.random() * 35));
  }
  await new Promise(r => setTimeout(r, 1200));

  // 3. Move mouse naturally to generate button
  const btn = page.locator('.generate-icon-button, button[aria-label*="Bắt đầu tạo" i]').first();
  const btnBox = await btn.boundingBox();
  if (btnBox) {
    console.log('Moving mouse to generate button...');
    await humanMouseMove(page, btnBox.x + btnBox.width / 2, btnBox.y + btnBox.height / 2);
    // Hover on button like a human
    await new Promise(r => setTimeout(r, 600 + Math.random() * 400));
    console.log('Clicking generate...');
    await page.mouse.down();
    await new Promise(r => setTimeout(r, 110));
    await page.mouse.up();
  } else {
    await btn.click();
  }

  await new Promise(r => setTimeout(r, 8000));
  page.off('response', onRes);
  await browser.close();

  if (rpcResult && rpcResult.includes('PUBLIC_ERROR')) {
    console.log('RESULT: FAILED WITH ERROR');
  } else if (rpcResult) {
    console.log('RESULT: SUCCESS!');
  } else {
    console.log('RESULT: NO RPC OBSERVED');
  }
}

testHumanFlow().catch(console.error);
