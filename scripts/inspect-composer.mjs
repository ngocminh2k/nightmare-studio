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

  const composerInfo = await flowPage.evaluate(() => {
    const promptBox = document.querySelector('flow-prompt-box, .prompt-box, .composer, footer, [role="region"]');
    const buttons = Array.from(document.querySelectorAll('button')).map(b => ({
      text: (b.innerText || '').trim(),
      ariaLabel: b.getAttribute('aria-label'),
      role: b.getAttribute('role'),
    })).filter(b => b.text || b.ariaLabel).slice(-25);

    return {
      composerTag: promptBox?.tagName,
      composerClass: promptBox?.className,
      recentButtons: buttons,
    };
  });

  console.log('Composer info:', JSON.stringify(composerInfo, null, 2));
  await browser.close();
}

main().catch(console.error);
