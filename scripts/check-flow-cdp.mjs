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
  console.log('Flow Page URL:', flowPage.url());
  const title = await flowPage.title();
  console.log('Flow Page Title:', title);

  // Check buttons, overlays, dialogs, progress
  const info = await flowPage.evaluate(() => {
    const btns = Array.from(document.querySelectorAll('button')).map(b => (b.innerText || b.getAttribute('aria-label') || '').trim()).filter(Boolean);
    const videos = Array.from(document.querySelectorAll('video')).map(v => ({ src: v.src, readyState: v.readyState }));
    const downloadBtns = Array.from(document.querySelectorAll('button')).filter(b => /download|tải/i.test(b.innerText || b.getAttribute('aria-label') || '')).map(b => (b.innerText || b.getAttribute('aria-label') || '').trim());
    const toasts = Array.from(document.querySelectorAll('.mat-snack-bar-container, .toast, .banner')).map(t => (t.innerText || '').trim());
    return {
      totalButtons: btns.length,
      downloadButtons: downloadBtns,
      videos: videos.length,
      toasts,
    };
  });
  console.log('Flow Page Info:', JSON.stringify(info, null, 2));
}

main().catch(err => console.error(err));
