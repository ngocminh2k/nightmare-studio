import { chromium } from 'playwright-core';

async function main() {
  const browser = await chromium.connectOverCDP('http://127.0.0.1:9222');
  const context = browser.contexts()[0];
  const pages = context.pages();
  const flowPage = pages.find(p => p.url().includes('flow.google.com'));
  if (!flowPage) {
    console.log('No Flow page found');
    await browser.close();
    return;
  }

  const cards = await flowPage.evaluate(() => {
    // Find all download buttons and their parent containers
    const dlBtns = Array.from(document.querySelectorAll('button')).filter(b =>
      /download|tải/i.test(b.innerText || b.getAttribute('aria-label') || '')
    );
    return dlBtns.map((b, idx) => {
      const parent = b.closest('.gallery-item, .card, .history-item, .asset-card, div[role="listitem"]') || b.parentElement?.parentElement;
      const imgs = Array.from((parent || document).querySelectorAll('img')).map(i => i.src?.slice(0, 100));
      const vids = Array.from((parent || document).querySelectorAll('video')).map(v => v.src?.slice(0, 100));
      return {
        idx,
        btnText: b.innerText,
        ariaLabel: b.getAttribute('aria-label'),
        parentClass: parent?.className,
        imgs: imgs.slice(0, 3),
        vids: vids.slice(0, 3),
      };
    });
  });

  console.log('Download Buttons & Cards:', JSON.stringify(cards, null, 2));
  await browser.close();
}

main().catch(console.error);
