import { chromium } from 'playwright-core';

async function main() {
  const browser = await chromium.connectOverCDP('http://127.0.0.1:9222');
  const page = browser.contexts()[0].pages().find(p => p.url().includes('flow'));
  if (page) {
    const info = await page.evaluate(() => {
      const g = window['grecaptcha'];
      return {
        hasGrecaptcha: !!g,
        hasEnterprise: !!(g && g['enterprise']),
      };
    });
    console.log('reCAPTCHA info:', info);
  }
  await browser.close();
}

main().catch(console.error);
