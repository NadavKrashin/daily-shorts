const { chromium } = require('playwright');
(async () => { const b = await chromium.launch(); const p = await b.newPage({viewport:{width:1280,height:720}});
 for (const [h,o] of [['arch.html','architecture-diagram.png'],['flow.html','user-flow-diagram.png']]) {
  await p.goto('file://' + process.cwd() + '/' + h); await p.screenshot({path:o, fullPage:true}); }
 await b.close(); })();
