import { chromium } from 'playwright-core';

async function main() {
  const browser = await chromium.connectOverCDP('http://127.0.0.1:9222');
  const page = browser.contexts()[0].pages().find(p => p.url().includes('0e935f47-3f1e-4546-9972-431b328de86f'));
  if (page) {
    console.log('Capturing console logs from page...');
    page.on('console', msg => {
      const text = msg.text();
      if (text.includes('error') || text.includes('warning') || text.includes('batch') || text.includes('policy') || text.includes('recaptcha')) {
        console.log(`[PAGE CONSOLE] ${msg.type()}: ${text}`);
      }
    });

    // Check prompt box
    const promptBox = page.locator('flow-prompt-box [contenteditable="true"]').first();
    const text = await promptBox.innerText().catch(() => '');
    console.log('Prompt box current text:', text);

    // Check if any error/dialog is visible
    const dialogs = await page.$$eval('[role="dialog"], .cdk-overlay-pane, mat-snack-bar-container', els => els.map(e => e.innerText));
    console.log('Visible dialogs/overlays:', dialogs);
  }
  await browser.close();
}

main().catch(console.error);
