import { chromium } from 'playwright-core';

async function main() {
  const browser = await chromium.connectOverCDP('http://127.0.0.1:9222');
  const page = browser.contexts()[0].pages().find(p => p.url().includes('flow'));
  if (page) {
    // Check credit info from the nzlxg RPC response (credits remaining)
    const creditEl = await page.$eval(
      '[aria-label*="credit" i], [aria-label*="tín dụng" i], .credits-remaining, flow-credits, [class*="credit"]',
      el => el.innerText
    ).catch(() => null);
    console.log('Credit element:', creditEl);

    // Try evaluating from page data
    const creditInfo = await page.evaluate(() => {
      // Find any text containing credit numbers
      const all = document.body.innerText;
      const matches = all.match(/(\d+)\s*(credit|tín dụng|Flow credit)/gi);
      return matches;
    });
    console.log('Credit text found:', creditInfo);
  }
  await browser.close();
}

main().catch(console.error);
