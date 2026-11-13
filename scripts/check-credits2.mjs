import { chromium } from 'playwright-core';

async function main() {
  const browser = await chromium.connectOverCDP('http://127.0.0.1:9222');

  // The nzlxg RPC returns credit info: [254,1,2,2,null,254,[reset_timestamp,remaining]]
  // Let's intercept it fresh
  const page = browser.contexts()[0].pages().find(p => p.url().includes('flow'));
  if (page) {
    let creditData = null;
    const onRes = async res => {
      if (res.url().includes('batchexecute')) {
        const text = await res.text().catch(() => '');
        if (text.includes('nzlxg')) {
          // Extract the nzlxg payload
          const match = text.match(/nzlxg","(\[.*?\])"/);
          if (match) creditData = match[1];
        }
      }
    };
    page.on('response', onRes);
    await page.reload({ waitUntil: 'networkidle' });
    await new Promise(r => setTimeout(r, 5000));
    page.off('response', onRes);
    console.log('nzlxg credit data:', creditData);

    // Also check page text for numbers near credit
    const txt = await page.evaluate(() => document.body.innerText);
    const lines = txt.split('\n').filter(l => /\d/.test(l) && /credit|tín dụng/i.test(l));
    console.log('Credit lines:', lines.slice(0, 5));
  }
  await browser.close();
}

main().catch(console.error);
