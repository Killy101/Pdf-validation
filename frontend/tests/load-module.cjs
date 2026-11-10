// Loads a TypeScript/TSX source file as CommonJS, replacing the named imports with test doubles.
const fs = require('node:fs');
const ts = require('typescript');

function load(file, dependencies = {}) {
  const module = {exports: {}};
  const code = ts.transpileModule(fs.readFileSync(file, 'utf8'), {
    compilerOptions: {module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX},
  }).outputText;
  new Function('require', 'exports', 'module', code)(name => dependencies[name] || require(name), module.exports, module);
  return module.exports;
}

module.exports = {load};
