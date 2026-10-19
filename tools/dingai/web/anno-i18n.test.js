/* The page catalog and i18n/strings.json stay the same. */
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert');

const json = JSON.parse(fs.readFileSync(path.join(__dirname, '../i18n/strings.json'), 'utf8'));
const src = fs.readFileSync(path.join(__dirname, 'anno.js'), 'utf8');
const m = src.match(/\/\* @i18n-start \*\/([\s\S]*?)\/\* @i18n-end \*\//);
assert.ok(m, 'i18n block missing');
const ctx = { window: { DINGAI_LANG: 'vi' }, localStorage: { getItem: function () { return ''; } }, navigator: { language: 'en' } };
vm.runInNewContext(m[1], ctx);
assert.deepStrictEqual(JSON.parse(JSON.stringify(ctx.STRINGS)), json);
assert.strictEqual(ctx.t('save'), 'Lưu');
ctx.window.DINGAI_LANG = 'en';
assert.strictEqual(ctx.t('save'), 'Save');
Object.keys(json).forEach(function (key) {
  ['zh', 'en', 'vi'].forEach(function (lang) {
    assert.ok(json[key][lang], key + ' ' + lang);
  });
});
console.log('anno-i18n ok');
