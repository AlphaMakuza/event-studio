// Local Chrome QA: real mobile emulation, layout checks, motion controls, screenshots.
import {spawn} from 'node:child_process';
import {existsSync, readFileSync, writeFileSync, mkdirSync} from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';

const root = path.resolve(import.meta.dirname, '..');
const profile = path.join(root, 'artifacts', `site-browser-${Date.now()}`);
mkdirSync(profile, {recursive: true});
const chrome = spawn('C:/Program Files/Google/Chrome/Application/chrome.exe', [
  '--headless', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
  '--disable-background-networking', '--disable-sync', '--remote-debugging-port=0',
  `--user-data-dir=${profile}`, 'about:blank'
], {stdio: 'ignore', windowsHide: true});
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
let ws;
try {
  const activePort = path.join(profile, 'DevToolsActivePort');
  for (let i = 0; i < 100 && !existsSync(activePort); i++) await delay(100);
  assert.ok(existsSync(activePort), 'Chrome debugging endpoint did not start');
  const port = readFileSync(activePort, 'utf8').split('\n')[0];
  const response = await fetch(`http://127.0.0.1:${port}/json/new?about:blank`, {method: 'PUT'});
  const target = await response.json();
  ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {ws.addEventListener('open', resolve, {once: true}); ws.addEventListener('error', reject, {once: true});});
  let id = 0;
  const pending = new Map();
  ws.addEventListener('message', event => {
    const data = JSON.parse(event.data);
    if (pending.has(data.id)) {
      const {resolve, reject} = pending.get(data.id); pending.delete(data.id);
      data.error ? reject(new Error(data.error.message)) : resolve(data.result);
    }
  });
  const call = (method, params = {}) => new Promise((resolve, reject) => {
    const number = ++id; pending.set(number, {resolve, reject});
    ws.send(JSON.stringify({id: number, method, params}));
  });
  const evaluate = async expression => (await call('Runtime.evaluate', {expression, returnByValue: true, awaitPromise: true})).result.value;
  await call('Page.enable');
  for (const [name, width, height, mobile] of [['desktop', 1440, 1000, false], ['mobile', 390, 844, true]]) {
    await call('Emulation.setDeviceMetricsOverride', {width, height, deviceScaleFactor: 1, mobile});
    await call('Page.navigate', {url: 'http://127.0.0.1:8765/'});
    await delay(2000);
    const layout = await evaluate(`({width:innerWidth, client:document.documentElement.clientWidth, scroll:document.documentElement.scrollWidth, videos:[...document.querySelectorAll('video')].map(v=>({ready:v.readyState,muted:v.muted,active:v.classList.contains('is-active'),playing:!v.paused})),hero:document.querySelector('.hero').getBoundingClientRect().width})`);
    assert.ok(layout.scroll <= width, `${name}: horizontal overflow ${JSON.stringify(layout)}`);
    assert.ok(layout.videos.length === 5 && layout.videos.every(v => v.muted), 'Expected five muted scenes');
    assert.equal(layout.videos.filter(v => v.active).length, 1, 'More than one scene is visible');
    assert.equal(layout.videos.filter(v => v.playing).length, 1, 'Only the current scene should play');
    assert.ok(layout.videos.find(v => v.active).ready >= 2, 'Active scene did not load');
    assert.equal(Math.round(layout.hero), layout.client, 'Hero does not fill the viewport');
    assert.ok(await evaluate(`!document.querySelector('#motion-toggle') && !document.querySelector('#motion-next') && !document.querySelector('.hero-copy a[href="#download"]') && !document.querySelector('header a[href="#download"]')`), 'Removed hero controls or download links are still present');
    assert.ok(await evaluate(`document.querySelector('.hero-mark img').complete && document.querySelector('.hero-mark img').naturalWidth > 0`), 'Hero logo did not load');
    assert.ok(await evaluate(`document.querySelector('video.is-active').videoWidth === 1920 && document.querySelector('video.is-active').videoHeight === 1080`), 'Hero clip is not Full HD');
    assert.equal(await evaluate(`document.querySelector('nav a').textContent.trim()`), 'Software', 'Navigation label is incorrect');
    const photos = await evaluate(`(async()=>{const images=[...document.querySelectorAll('.applications img')];for(const image of images){image.loading='eager';await image.decode();}return images.map(image=>({width:image.naturalWidth,height:image.naturalHeight}));})()`);
    assert.ok(photos.length === 2 && photos[0].width === 1500 && photos[0].height === 568 && photos[1].width === 1597 && photos[1].height === 949, 'Industry images must load at their expected source resolutions');
    assert.ok(await evaluate(`document.querySelector('.applications img').currentSrc.startsWith('data:image/jpeg;base64,')`), 'Event camera output must be embedded with the page');
    assert.ok(await evaluate(`!document.querySelector('.inspection-region, .inspection-key')`), 'Unwanted inspection labels are still present');
    const metrics = await call('Page.getLayoutMetrics');
    const image = await call('Page.captureScreenshot', {format: 'png', captureBeyondViewport: true,
      clip: {x: 0, y: 0, width, height: Math.ceil(metrics.cssContentSize.height), scale: 1}});
    writeFileSync(path.join(root, 'artifacts', `site-purple-${name}.png`), Buffer.from(image.data, 'base64'));
    for (let i = 0; i < 5; i++) {
      const previous = await evaluate(`document.querySelector('.hero-media video.is-active').dataset.title`);
      await evaluate(`advance()`);
      const current = await evaluate(`document.querySelector('.hero-media video.is-active').dataset.title`);
      assert.notEqual(current, previous, 'Scene did not advance');
      assert.ok(await evaluate(`document.querySelector('video.is-active').videoWidth === 1920 && document.querySelector('video.is-active').videoHeight === 1080`), 'A scene is not Full HD');
    }
    const previous = await evaluate(`document.querySelector('.hero-media video.is-active').dataset.title`);
    for (let n = 0; n < 100 && await evaluate(`document.querySelector('.hero-media video.is-active').dataset.title`) === previous; n++) await delay(100);
    const state = await evaluate(`({title:document.querySelector('.hero-media video.is-active').dataset.title, wantsMotion, visible, hidden:document.hidden, paused:document.querySelector('.hero-media video.is-active').paused, ended:document.querySelector('.hero-media video.is-active').ended,time:document.querySelector('.hero-media video.is-active').currentTime,duration:document.querySelector('.hero-media video.is-active').duration})`);
    assert.notEqual(state.title, previous, 'Automatic scene rotation failed: ' + JSON.stringify(state));
    await evaluate(`window.scrollTo(0, document.querySelector('#software').offsetTop + 100)`);
    await delay(250);
    assert.ok(await evaluate(`[...document.querySelectorAll('video')].every(v=>v.paused)`), 'Offscreen clips did not pause');
    await evaluate(`window.scrollTo(0, 0)`);
    await delay(350);
    assert.ok(await evaluate(`!document.querySelector('video.is-active').paused`), 'Slideshow did not resume on return');
    console.log(`PASS ${name}: ${width}px, logo loaded, no hero controls/downloads, five Full HD scenes, automatic cycling.`);
  }
  await call('Emulation.setEmulatedMedia', {features: [{name: 'prefers-reduced-motion', value: 'reduce'}]});
  await call('Page.reload'); await delay(1000);
  assert.ok(await evaluate(`[...document.querySelectorAll('video')].every(v=>v.paused)`), 'Reduced-motion preference ignored');
  console.log('PASS: reduced-motion preference respected.');
  await call('Browser.close');
} finally {
  ws?.close();
  chrome.kill();
}
