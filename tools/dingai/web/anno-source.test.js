/* Runs the source-trace block inside anno.js. No browser, no extra package. */
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert');

const src = fs.readFileSync(path.join(__dirname, 'anno.js'), 'utf8');
const m = src.match(/\/\* @source-start \*\/([\s\S]*?)\/\* @source-end \*\//);
assert.ok(m, 'source block missing');
const ctx = { window: {} };
vm.runInNewContext(m[1], ctx);

const reactEl = {
  __reactFiber$abc: {
    type: { name: 'SaveButton' },
    _debugSource: { fileName: 'src/SaveButton.tsx', lineNumber: 42, columnNumber: 3 },
    return: { type: { name: 'Form' }, _debugSource: null }
  }
};
const hit = ctx.sourceFromElement(reactEl);
assert.strictEqual(hit.framework, 'react');
assert.strictEqual(hit.component, 'SaveButton');
assert.strictEqual(hit.file, 'src/SaveButton.tsx');
assert.strictEqual(hit.line, 42);

const vueEl = { parent: { __vueParentComponent: { type: { __file: 'src/Order.vue', __name: 'OrderPanel', __line: 8 } } } };
const vue = ctx.sourceFromElement(vueEl);
assert.strictEqual(vue.framework, 'vue');
assert.strictEqual(vue.file, 'src/Order.vue');
assert.strictEqual(vue.component, 'OrderPanel');
assert.strictEqual(vue.line, 8);

const plain = ctx.sourceFromElement({ parent: {} });
assert.strictEqual(plain, null);

const mapped = ctx.applySourceMap(
  { framework: 'bundle', component: '', file: 'main.js', line: 1, column: 1 },
  { file: 'main.js', sources: ['src/App.tsx'], mappings: 'AAAA' }
);
assert.strictEqual(mapped.file, 'src/App.tsx');
assert.strictEqual(mapped.line, 1);
assert.strictEqual(mapped.column, 1);

console.log('anno-source ok');
