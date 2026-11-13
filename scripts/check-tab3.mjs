import { chromium } from 'playwright-core';

async function main() {
  const browser = await chromium.connectOverCDP('http://127.0.0.1:9222');
  const context = browser.contexts()[0];
  const pages = context.pages();
  const p3 = pages.find(p => p.url().includes('6cb075cf-7b9e-4b65-b35c-24b363da057a'));
  if (p3) {
    console.log('Project 3 url:', p3.url());
    const alerts = await p3.$$eval('*', els =>
      els.filter(e => e.innerText && e.innerText.includes('hoạt động bất thường'))
         .map(e => ({ tag: e.tagName, text: e.innerText.slice(0, 200) }))
    );
    console.log('Alert elements found:', alerts.length);
    if (alerts.length > 0) {
      console.log('Top alert:', alerts[alerts.length - 1]);
    }
  }
  await browser.close();
}

main().catch(console.error);
