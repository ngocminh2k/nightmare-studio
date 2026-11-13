import { chromium } from 'playwright-core';

async function main() {
  const browser = await chromium.connectOverCDP('http://127.0.0.1:9222');
  const page = browser.contexts()[0].pages().find(p => p.url().includes('b8c98d11-92ce-430f-9114-f3f42c265cdf'));
  if (page) {
    const promptText = await page.locator('flow-prompt-box [contenteditable="true"]').first().innerText().catch(() => '');
    console.log('Prompt text in b8c:', promptText);
    const topBatch = page.locator('.batch-container').first();
    const batchText = await topBatch.innerText().catch(() => '');
    console.log('Top batch text in b8c:', batchText.slice(0, 200).replace(/\n+/g, ' '));
  }
  await browser.close();
}

main().catch(console.error);
