import { chromium } from 'playwright-core';
import { isFlowPage } from './flow-url.mjs';

async function main() {
  const browser = await chromium.connectOverCDP('http://127.0.0.1:9222');
  const context = browser.contexts()[0];
  const pages = context.pages();
  const flowPage = pages.find(p => isFlowPage(p.url()));
  if (!flowPage) {
    console.log('No Flow page found');
    await browser.close();
    return;
  }

  const details = await flowPage.evaluate(() => {
    // Check progress bars / spinners / loading
    const spinners = Array.from(document.querySelectorAll('mat-spinner, mat-progress-bar, .spinner, .loading, [role="progressbar"]')).map(el => el.outerHTML.slice(0, 100));

    // Check all buttons with "download"
    const dlButtons = Array.from(document.querySelectorAll('button')).filter(b =>
      /download|tải/i.test(b.innerText || b.getAttribute('aria-label') || '')
    );

    // Check cards / gallery items
    const allCards = Array.from(document.querySelectorAll('div, section, article')).filter(el => {
      return el.children.length > 0 && Array.from(el.querySelectorAll('button')).some(b => /download|tải/i.test(b.innerText || b.getAttribute('aria-label') || ''));
    }).slice(0, 5);

    return {
      spinners,
      dlButtonCount: dlButtons.length,
      dlButtonsInfo: dlButtons.map(b => ({
        text: b.innerText.trim(),
        ariaLabel: b.getAttribute('aria-label'),
        disabled: b.disabled,
        rect: b.getBoundingClientRect(),
        parentTag: b.parentElement?.tagName,
        parentClass: b.parentElement?.className,
      }))
    };
  });

  console.log('Page details:', JSON.stringify(details, null, 2));
  await browser.close();
}

main().catch(console.error);
