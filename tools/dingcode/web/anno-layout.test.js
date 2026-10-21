/* Runs the layoutCallouts block inside anno.js. No browser, no extra package. */
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert');

const src = fs.readFileSync(path.join(__dirname, 'anno.js'), 'utf8');
const m = src.match(/\/\* @layout-start \*\/([\s\S]*?)\/\* @layout-end \*\//);
assert.ok(m, 'layout block missing');
const ctx = {};
vm.runInNewContext(m[1], ctx);
const layout = ctx.layoutCallouts;
const bounds = { x: 0, y: 0, w: 800, h: 600 };

function hits(a, b) {
  const x1 = Math.max(a.x, b.x), y1 = Math.max(a.y, b.y);
  const x2 = Math.min(a.x + a.w, b.x + b.w), y2 = Math.min(a.y + a.h, b.y + b.h);
  return x2 > x1 && y2 > y1;
}

const one = layout([{ id: 1, ax: 100, ay: 100, w: 40, h: 20 }], [], bounds)[0];
assert.strictEqual(one.x, 118);
assert.strictEqual(one.y, 90);
assert.strictEqual(one.leader, true);

const two = layout([
  { id: 1, ax: 100, ay: 100, w: 80, h: 22 },
  { id: 2, ax: 110, ay: 100, w: 80, h: 22 }
], [], bounds);
assert.ok(!hits(
  { x: two[0].x, y: two[0].y, w: 80, h: 22 },
  { x: two[1].x, y: two[1].y, w: 80, h: 22 }
), JSON.stringify(two));

const edge = layout([{ id: 1, ax: 790, ay: 100, w: 80, h: 22 }], [], bounds)[0];
assert.ok(edge.x >= bounds.x && edge.x + 80 <= bounds.x + bounds.w, JSON.stringify(edge));
assert.ok(edge.y >= bounds.y && edge.y + 22 <= bounds.y + bounds.h, JSON.stringify(edge));

const blocked = layout(
  [{ id: 1, ax: 100, ay: 100, w: 40, h: 20 }],
  [{ x: 110, y: 80, w: 80, h: 40 }],
  bounds
)[0];
assert.ok(!hits(
  { x: blocked.x, y: blocked.y, w: 40, h: 20 },
  { x: 110, y: 80, w: 80, h: 40 }
), JSON.stringify(blocked));

console.log('anno-layout ok');
