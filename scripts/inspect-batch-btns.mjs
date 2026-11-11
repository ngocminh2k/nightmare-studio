import { chromium } from 'playwright-core';

async function main() {
  const browser = await chromium.connectOverCDP('http://127.0.0.1:9222');
  const page = browser.contexts()[0].pages().find(p => p.url().includes('0e935f47-3f1e-4546-9972-431b328de86f'));
  if (page) {
    const batches = await page.$$eval('.batch-container', els => els.map(el => {
      const btns = Array.from(el.querySelectorAll('button')).map(b => ({
        text: b.innerText.trim(),
        label: b.getAttribute('aria-label') || '',
        cls: b.className,
      }));
      return {
        text: el.innerText.slice(0, 100).replace(/\n+/g, ' '),
        btns,
      };
    }));
    console.log(JSON.stringify(batches.slice(0, 3), null, 2));
  }
  await browser.close();
}

main().catch(console.error);
