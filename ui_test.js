#!/usr/bin/env node
/**
 * 端到端验收 —— 零依赖，用 CDP 驱动本机 Chrome/Edge 打开真实页面。
 *
 * 覆盖：
 *   1. 四条结局路径（数值与 ending_balance.md 一致）
 *   2. 存读档往返
 *   3. v1 旧档清理
 *   4. 375×812 窄屏溢出
 *   5. clamp 截断时飘字报「实际入账」而非原始 delta
 *   6. 存档时机：replies 中途关闭 → 重播本章、不重复结算；播放中手动存档被拒
 *   7. 全流程未捕获错误
 *
 * 用法: node ui_test.js
 * 退出码: 0 全绿 / 1 有失败 / 2 环境错误
 */
const { spawn } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');

const PAGE_FILE = path.join(__dirname, 'index.html');
const PAGE = 'file:///' + encodeURI(PAGE_FILE.replace(/\\/g, '/'));
const PORT = 9500 + Math.floor(Math.random() * 200);

const CANDIDATES = [
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  '/usr/bin/google-chrome',
  '/usr/bin/chromium',
];
const CHROME = CANDIDATES.find(p => { try { return fs.statSync(p).isFile(); } catch (e) { return false; } });
if (!CHROME) { console.error('找不到 Chrome/Edge，无法运行 UI 测试'); process.exit(2); }
if (!fs.existsSync(PAGE_FILE)) { console.error('缺少 index.html:', PAGE_FILE); process.exit(2); }

const sleep = ms => new Promise(r => setTimeout(r, ms));
const rows = [];
function check(name, actual, pass) { rows.push({ name, actual, pass: !!pass }); }

const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'avg-'));
const child = spawn(CHROME, ['--headless=new', '--remote-debugging-port=' + PORT,
  '--user-data-dir=' + profile, '--disable-gpu', '--no-first-run', '--window-size=1280,900',
  'about:blank'], { stdio: 'ignore' });

let ws, msgId = 0;
const pending = new Map();
function send(method, params = {}) {
  return new Promise((resolve, reject) => {
    const id = ++msgId;
    pending.set(id, { resolve, reject });
    ws.send(JSON.stringify({ id, method, params }));
    setTimeout(() => { if (pending.has(id)) { pending.delete(id); reject(new Error('timeout ' + method)); } }, 40000);
  });
}
async function ev(expr) {
  const r = await send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true, userGesture: true });
  if (r.exceptionDetails) throw new Error('页面异常: ' + JSON.stringify(r.exceptionDetails.exception));
  return r.result.value;
}
async function goto(url) {
  await send('Page.navigate', { url: url || PAGE });
  for (let i = 0; i < 200; i++) {
    try { if (await ev('document.readyState') === 'complete') { await sleep(200); return; } } catch (e) {}
    await sleep(50);
  }
  throw new Error('页面未就绪');
}

/* 页面内积木：被拼进每段 evaluate，避免各段重复实现 */
const HELPERS = `
  const $ = id => document.getElementById(id);
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const panel = () => [+$('v-share').textContent, +$('v-care').textContent, +$('v-pat').textContent];
  const save = () => { const r = localStorage.getItem('luyangrui_save_v2'); return r ? JSON.parse(r) : null; };
  const floats = () => [...document.querySelectorAll('.stat-float')].map(n => n.textContent);
  const waitChoices = async (ms) => { const t0 = Date.now();
    while (Date.now() - t0 < ms) { const b = document.querySelectorAll('#choices .choice');
      if (b.length) return b; $('log').click(); await sleep(40); } return []; };
  const waitText = async (needle, ms) => { const t0 = Date.now();
    while (Date.now() - t0 < ms) { if ($('log').textContent.indexOf(needle) >= 0) return true;
      $('log').click(); await sleep(60); } return false; };
`;

(async () => {
  let target = null;
  for (let i = 0; i < 100; i++) {
    try {
      const list = await (await fetch('http://127.0.0.1:' + PORT + '/json/list')).json();
      target = list.find(t => t.type === 'page');
      if (target) break;
    } catch (e) {}
    await sleep(150);
  }
  if (!target) throw new Error('无法连接 headless 浏览器');

  ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
  ws.onmessage = e => {
    const m = JSON.parse(e.data);
    if (m.id && pending.has(m.id)) {
      const { resolve, reject } = pending.get(m.id);
      pending.delete(m.id);
      m.error ? reject(new Error(m.error.message)) : resolve(m.result);
    }
  };
  await send('Page.enable');
  await send('Runtime.enable');

  // 错误监听：全程有效
  await send('Page.addScriptToEvaluateOnNewDocument', {
    source: `window.__errs = []; window.addEventListener('error', e => window.__errs.push(String(e.message)));
             window.addEventListener('unhandledrejection', e => window.__errs.push('rej:' + e.reason));`
  });
  // 计时器加速：只用于「跑完整局」类用例，测存档/飘字前会移除
  const accel = await send('Page.addScriptToEvaluateOnNewDocument', {
    source: `(() => { const st = window.setTimeout; window.setTimeout = (fn, ms, ...a) => st(fn, ms > 40 ? 10 : ms, ...a); })();`
  });

  /* ---------- 1. 四条结局路径 ---------- */
  const PATHS = [
    ['3322212332', '甜', [86, 88, 34]],
    ['3223222233', '暖', [31, 72, 75]],
    ['2131333121', '遗憾', [38, 53, 71]],
    ['1111131111', '疏离', [100, 36, 20]],
  ];
  for (const [p, name, want] of PATHS) {
    await goto();
    const out = await ev(`(async () => { ${HELPERS}
      $('input-name').value = '回归';
      $('btn-start').click();
      let i = 0;
      for (let g = 0; g < 8000; g++) {
        if ($('screen-end').classList.contains('active')) break;
        $('log').click();
        const b = document.querySelectorAll('#choices .choice');
        if (b.length && i < 10) { b[+'${p}'[i] - 1].click(); i++; }
        await sleep(15);
      }
      await sleep(200);
      return { clicked: i, ended: $('screen-end').classList.contains('active'),
               title: $('end-title').textContent, stats: panel(),
               endStats: [...document.querySelectorAll('#end-stats b')].map(b => +b.textContent) };
    })()`);
    check(p + ' → ' + name + ' ' + want.join('/'),
      out.title + ' ' + out.stats.join('/'),
      out.ended && out.clicked === 10 && out.stats.join('/') === want.join('/') &&
      out.endStats.join('/') === want.join('/') && out.title.indexOf(name) >= 0);
  }

  /* ---------- 2. 存读档往返 ---------- */
  await goto();
  const saved = await ev(`(async () => { ${HELPERS}
    localStorage.clear();
    $('input-name').value = '存档';
    $('btn-start').click();
    await waitChoices(20000);
    document.querySelectorAll('#choices .choice')[0].click();
    await waitText('第二章', 20000);                 // 切章后才落盘
    await sleep(300);
    return { panel: panel(), save: save() };
  })()`);
  await goto();
  const resumed = await ev(`(async () => { ${HELPERS}
    const visible = getComputedStyle($('btn-continue')).display !== 'none';
    $('btn-continue').click();
    await sleep(400);
    return { visible, panel: panel(), inCh2: $('log').textContent.indexOf('第二章') >= 0 };
  })()`);
  check('存读档往返', saved.panel.join('/') + ' → ' + resumed.panel.join('/') + ' @' + (saved.save && saved.save.scene),
    resumed.visible && resumed.inCh2 && resumed.panel.join('/') === saved.panel.join('/') &&
    saved.save && saved.save.scene === 's2');

  /* ---------- 3. v1 旧档清理 ---------- */
  await goto();
  await ev(`(() => { localStorage.clear();
    localStorage.setItem('luyangrui_save_v1', JSON.stringify({ name: '旧', fav: 10, dep: 10, cool: 50, scene: 's3' })); })()`);
  await goto();
  await sleep(900);
  const legacy = await ev(`({ v1: localStorage.getItem('luyangrui_save_v1'),
    cont: getComputedStyle(document.getElementById('btn-continue')).display,
    toast: document.getElementById('toast').textContent })`);
  check('v1 旧档清理 + 提示', 'v1=' + legacy.v1 + ' 继续=' + legacy.cont + ' 提示=' + legacy.toast,
    legacy.v1 === null && legacy.cont === 'none' && legacy.toast.indexOf('旧版本存档') >= 0);

  /* ---------- 4. 375 窄屏 ---------- */
  await send('Emulation.setDeviceMetricsOverride', { width: 375, height: 812, deviceScaleFactor: 2, mobile: true });
  await goto();
  const narrow = await ev(`(async () => { ${HELPERS}
    localStorage.clear();
    $('input-name').value = '窄屏';
    $('btn-start').click();
    await waitChoices(20000);
    document.querySelectorAll('#choices .choice')[0].click();
    await sleep(600);
    const bad = [...document.querySelectorAll('.start-card,.status,.log,.choices,.choice,.end-card')]
      .filter(e => e.getBoundingClientRect().right > 375.5 || e.scrollWidth > e.clientWidth + 1)
      .map(e => e.className);
    return { scrollWidth: document.documentElement.scrollWidth, innerWidth, bad };
  })()`);
  check('375×812 无溢出', 'scrollWidth=' + narrow.scrollWidth + ' 溢出=' + JSON.stringify(narrow.bad),
    narrow.scrollWidth <= 375 && narrow.innerWidth === 375 && narrow.bad.length === 0);
  await send('Emulation.clearDeviceMetricsOverride');

  /* ================= 以下用例需要真实计时，先关掉加速 ================= */
  await send('Page.removeScriptToEvaluateOnNewDocument', { identifier: accel.identifier });

  /* ---------- 5. clamp 截断：飘字必须是实际入账量 ---------- */
  // s3 第 1 项为 +10/-2/-6；把存档摊成 98/50/3 再读档
  await goto();
  await ev(`(() => { localStorage.clear();
    localStorage.setItem('luyangrui_save_v2', JSON.stringify(
      { name: '截断', gender: '女', share: 98, care: 50, pat: 3, scene: 's3' })); })()`);
  const clamped = await ev(`(async () => { ${HELPERS}
    $('btn-continue').click();
    await waitChoices(30000);
    const before = panel();
    document.querySelectorAll('#choices .choice')[0].click();
    await sleep(70);
    return { before, after: panel(), floats: floats() };
  })()`);
  check('clamp 前 98/50/3', clamped.before.join('/'), clamped.before.join('/') === '98/50/3');
  check('clamp 后 100/48/0', clamped.after.join('/'), clamped.after.join('/') === '100/48/0');
  check('飘字为实际差值 +2/-2/-3', clamped.floats.join(' '), clamped.floats.join(' ') === '+2 -2 -3');
  check('未飘出原始 +10', clamped.floats.join(' '), clamped.floats.indexOf('+10') < 0);

  // 已饱和：差值归零 → 该项不飘字（只保留另外两条）
  await goto();
  await ev(`(() => { localStorage.clear();
    localStorage.setItem('luyangrui_save_v2', JSON.stringify(
      { name: '饱和', gender: '女', share: 100, care: 50, pat: 50, scene: 's3' })); })()`);
  const saturated = await ev(`(async () => { ${HELPERS}
    $('btn-continue').click();
    await waitChoices(30000);
    document.querySelectorAll('#choices .choice')[0].click();
    await sleep(70);
    return { floats: floats(), after: panel() };
  })()`);
  check('已饱和项不飘字（只剩 -2 -6）', saturated.floats.join(' '), saturated.floats.join(' ') === '-2 -6');
  check('饱和后属性 100/48/44', saturated.after.join('/'), saturated.after.join('/') === '100/48/44');

  /* ---------- 6. 存档时机：replies 中途关闭 ---------- */
  await goto();
  const mid = await ev(`(async () => { ${HELPERS}
    localStorage.clear();
    $('input-name').value = '重载';
    $('btn-start').click();
    await waitChoices(30000);
    document.querySelectorAll('#choices .choice')[0].click();   // s1 第 1 项 → 25/49/57
    await sleep(150);                                          // 仍在播 replies
    $('btn-save').click();                                     // 手动存档应被拒
    await sleep(60);
    return { toast: $('toast').textContent, save: save(), panel: panel() };
  })()`);
  check('播放中手动存档被拒', mid.toast, mid.toast.indexOf('播放中') >= 0);
  check('播放中磁盘存档仍是本章开局',
    mid.save && mid.save.scene + ' ' + [mid.save.share, mid.save.care, mid.save.pat].join('/'),
    mid.save && mid.save.scene === 's1' && mid.save.share === 15 && mid.save.care === 56 && mid.save.pat === 60);

  await goto();                                                 // 等价于「切出去又回来」
  const replayed = await ev(`(async () => { ${HELPERS}
    const visible = getComputedStyle($('btn-continue')).display !== 'none';
    $('btn-continue').click();
    await sleep(300);
    const onLoad = panel();
    const inCh1 = $('log').textContent.indexOf('第一章') >= 0;
    await waitChoices(30000);
    document.querySelectorAll('#choices .choice')[0].click();
    await sleep(200);
    const afterPick = panel();
    await waitText('第二章', 30000);
    await sleep(300);
    return { visible, onLoad, inCh1, afterPick, inCh2: $('log').textContent.indexOf('第二章') >= 0, save: save() };
  })()`);
  check('重载后可继续（按钮可见）', replayed.visible, replayed.visible);
  check('读档回到第一章开头', replayed.inCh1 + ' ' + replayed.onLoad.join('/'),
    replayed.inCh1 && replayed.onLoad.join('/') === '15/56/60');
  check('重选后 25/49/57（未重复结算）', replayed.afterPick.join('/'),
    replayed.afterPick.join('/') === '25/49/57');
  check('（对照）重复结算会是 35/42/54', replayed.afterPick.join('/'),
    replayed.afterPick.join('/') !== '35/42/54');
  check('进入第二章后存档推进到 s2', replayed.save && replayed.save.scene + ' ' + replayed.save.share,
    replayed.inCh2 && replayed.save.scene === 's2' && replayed.save.share === 25);

  /* ---------- 7. 未捕获错误 ---------- */
  const errs = await ev('window.__errs || []');
  check('全流程无未捕获错误', JSON.stringify(errs), errs.length === 0);

  /* ---------- 汇总 ---------- */
  console.log('');
  rows.forEach(r => console.log((r.pass ? 'PASS  ' : 'FAIL  ') + r.name + '  ->  ' + r.actual));
  const bad = rows.filter(r => !r.pass);
  console.log('\n判定: ' + (bad.length ? 'FAILED (' + bad.length + '/' + rows.length + ')' : 'ALL PASS (' + rows.length + '/' + rows.length + ')'));
  try { child.kill(); } catch (e) {}
  process.exit(bad.length ? 1 : 0);
})().catch(e => {
  console.error('ERROR', e);
  try { child.kill(); } catch (x) {}
  process.exit(2);
});
