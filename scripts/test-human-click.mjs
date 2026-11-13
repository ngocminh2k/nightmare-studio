import { chromium } from 'playwright-core';

async function main() {
  const browser = await chromium.connectOverCDP('http://127.0.0.1:9222');
  const context = browser.contexts()[0];
  const page = context.pages().find(p => p.url().includes('0e935f47-3f1e-4546-9972-431b328de86f'));
  if (page) {
    console.log('Testing generate on project 0e9...');
    // Focus prompt box
    const promptBox = page.locator('flow-prompt-box [contenteditable="true"]').first();
    await promptBox.click();
    await page.keyboard.press('Control+A');
    await page.keyboard.type('A quiet autumn forest at twilight, volumetric fog, dark comic book art style.');
    await new Promise(r => setTimeout(r, 1000));

    // Find generate button
    const btn = page.locator('button.create-btn, button:has-text("arrow_forward"), button:has-text("Tạo")').first();
    const box = await btn.boundingBox();
    console.log('Button box:', box);

    if (box) {
      // Move mouse naturally
      await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2, { steps: 15 });
      await new Promise(r => setTimeout(r, 500));
      await page.mouse.down();
      await new Promise(r => setTimeout(r, 120));
      await page.mouse.up();
      console.log('Mouse click performed.');
    }

    // Wait and watch top batch
    for (let i = 0; i < 15; i++) {
      await new Promise(r => setTimeout(r, 2000));
      const topBatch = page.locator('.batch-container').first();
      const text = await topBatch.innerText().catch(() => '');
      console.log(`[${i * 2}s] Top batch status:`, text.slice(0, 100).replace(/\n+/g, ' '));
      if (text.includes('Không thành công')) {
        console.log('Hit error:', text);
        break;
      }
      if (text.includes('Ảnh đã tải lên') || text.includes('16:9')) {
        const hasImg = await topBatch.locator('img').count();
        if (hasImg > 0) {
          console.log('Success! Image rendered!');
          break;
        }
      }
    }
  }
  await browser.close();
}

main().catch(console.error);
