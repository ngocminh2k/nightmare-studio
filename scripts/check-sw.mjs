import { chromium } from 'playwright-core';

async function main() {
  const browser = await chromium.connectOverCDP('http://127.0.0.1:9222');
  const page = browser.contexts()[0].pages().find(p => p.url().includes('flow'));
  if (page) {
    const sw = await page.evaluate(async () => {
      const registrations = await navigator.serviceWorker?.getRegistrations() || [];
      return registrations.map(r => r.scope);
    });
    console.log('Service Workers:', sw);
  }
  await browser.close();
}

main().catch(console.error);
