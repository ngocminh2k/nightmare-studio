import { chromium } from 'playwright-core';

async function main() {
  const browser = await chromium.connectOverCDP('http://127.0.0.1:9222');
  const page = browser.contexts()[0].pages().find(p => p.url().includes('flow.google.com'));
  if (!page) {
    console.log('No Flow page found');
    await browser.close();
    return;
  }

  // Find asset-item for scene-001.png
  const card = page.locator('.cdk-overlay-pane .asset-item').filter({ hasText: 'scene-001.png' }).first();
  console.log('Found card count:', await card.count());
  await card.click();
  await page.waitForTimeout(500);

  // Find detail-add-to-prompt-btn
  const addBtn = page.locator('.detail-add-to-prompt-btn, button:has-text("Thêm vào câu lệnh"), button:has-text("Thêm")').first();
  console.log('Found addBtn count:', await addBtn.count(), 'text:', await addBtn.innerText());
  await addBtn.click();
  await page.waitForTimeout(1000);

  // Now inspect .frame-trigger in prompt box!
  const triggerInfo = await page.evaluate(() => {
    const triggers = Array.from(document.querySelectorAll('.frame-trigger'));
    return triggers.map((t, idx) => ({
      idx,
      text: t.innerText.trim(),
      html: t.innerHTML.slice(0, 300),
      hasImg: Boolean(t.querySelector('img')),
      imgSrc: t.querySelector('img')?.src || null,
    }));
  });

  console.log('Trigger info after clicking Thêm:', JSON.stringify(triggerInfo, null, 2));
  await browser.close();
}

main().catch(console.error);
