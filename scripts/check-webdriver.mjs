import { chromium } from 'playwright-core';

async function main() {
  const browser = await chromium.connectOverCDP('http://127.0.0.1:9222');
  const page = browser.contexts()[0].pages().find(p => p.url().includes('0e935f47-3f1e-4546-9972-431b328de86f'));
  if (page) {
    const isWd = await page.evaluate(() => navigator.webdriver);
    console.log('navigator.webdriver =', isWd);
  }
  await browser.close();
}

main().catch(console.error);
