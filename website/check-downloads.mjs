import assert from 'node:assert/strict';
import {readFileSync, existsSync} from 'node:fs';
import {webcrypto} from 'node:crypto';
import path from 'node:path';
import vm from 'node:vm';

const root = process.argv[2] ? path.resolve(process.argv[2]) : path.resolve(import.meta.dirname, 'dist');
const html = readFileSync(path.join(root, 'index.html'), 'utf8');
for (const [, target] of html.matchAll(/(?:src|href)="([^"]+)"/g)) {
  if (target.startsWith('#')) {
    if (target.length > 1) assert.ok(html.includes(`id="${target.slice(1)}"`), `Missing anchor ${target}`);
  } else if (target.startsWith('data:image/jpeg;base64,')) {
    const image = Buffer.from(target.slice('data:image/jpeg;base64,'.length), 'base64');
    assert.ok(image.length > 0 && image[0] === 0xff && image[1] === 0xd8, 'Invalid embedded JPEG');
    assert.ok(image.equals(readFileSync(path.join(root, 'assets/industry/event-camera-output.jpg'))), 'Embedded example does not match its credited image');
  } else if (!/^https?:/.test(target)) {
    assert.ok(existsSync(path.join(root, target)), `Missing asset ${target}`);
  }
}

const script = readFileSync(path.join(root, 'downloads.js'), 'utf8');
const status = {textContent: ''};
const buttons = ['application', 'source'].map(download => ({dataset: {download}, disabled: false,
  addEventListener(_, callback) { this.callback = callback; }}));
let corrupted = false;
const saved = [];
const context = vm.createContext({crypto: webcrypto, Blob,
  document: {querySelector: () => status, querySelectorAll: () => buttons,
    body: {appendChild() {}}, createElement() { return {click() {saved.push(this.download);}, remove() {}}; }},
  fetch: async name => {
    const data = readFileSync(path.join(root, name));
    if (corrupted && name.endsWith('.part')) data[0] ^= 1;
    return {ok: true, json: async () => JSON.parse(data.toString()),
      arrayBuffer: async () => data.buffer.slice(data.byteOffset, data.byteOffset + data.length)};
  }, URL: {createObjectURL: () => 'blob:test', revokeObjectURL() {}},
  setTimeout: callback => callback()
});
vm.runInContext(script, context);
await buttons[0].callback();
assert.ok(saved[0]?.includes('windows-x64'), status.textContent);
await buttons[1].callback();
assert.ok(saved[1]?.includes('corresponding-source'), status.textContent);
corrupted = true;
await buttons[0].callback();
assert.equal(saved.length, 2, 'A corrupted download was saved');
assert.ok(status.textContent.includes('Checksum mismatch'), status.textContent);
assert.ok(buttons.every(button => !button.disabled));
console.log('PASS: local links/assets, both download flows, SHA-256 rejection, and control recovery.');
