import { chromium } from 'playwright-core';

async function testNewProject() {
  const browser = await chromium.connectOverCDP('http://127.0.0.1:9222');
  const context = browser.contexts()[0];
  const page = await context.newPage();
  console.log('Navigating to flow home...');
  await page.goto('https://labs.google/fx/vi/tools/flow', { waitUntil: 'networkidle' });
  await new Promise(r => setTimeout(r, 4000));

  console.log('Current URL:', page.url());
  // Find "Dự án mới" / "New project"
  const newBtn = page.locator('button:has-text("Dự án mới"), button:has-text("New project"), a:has-text("Dự án mới")').first();
  if (await newBtn.isVisible().catch(() => false)) {
    console.log('Clicking New Project...');
    await newBtn.click();
    await new Promise(r => setTimeout(r, 5000));
    console.log('New project URL:', page.url());
  } else {
    console.log('New project button not found, listing buttons:');
    const btns = await page.$$eval('button', els => els.map(b => b.innerText.trim()).filter(Boolean));
    console.log(btns.slice(0, 15));
  }

  await page.close();
  await browser.close();
}

testNewProject().catch(console.error);
