'use strict';

/* One headless runner, shared by the test suite and by measure.js, so the numbers
   in the README are generated from the shipped file rather than copied by hand
   from a session that used different constants.

   Two loaders, because there are two things to test and only one of them is a
   page. The behaviour tests `require('./tornado.js')` directly -- no DOM, no vm,
   no clock -- because the model is now a module rather than a block welded into
   the page. The workspace tests use `loadSim`, which loads index.html the way the
   bridge serves it: every <script> in document order, a `src` one read from disk,
   anything else inline. Both reach the same simulation source, so the browser and
   the suite cannot drift apart. */

const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const HTML_PATH = path.join(__dirname, 'index.html');

/* The scripts the page actually loads, in document order. */
function scriptsIn(html) {
  const out = [];
  for (const match of html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/gi)) {
    const src = /\bsrc\s*=\s*["']([^"']+)["']/i.exec(match[1]);
    out.push({ src: src ? src[1].trim() : '', code: src ? '' : match[2] });
  }
  if (!out.length) throw new Error('index.html loads no scripts');
  return out;
}

const readFile = name => fs.readFileSync(path.join(__dirname, name), 'utf8');

/* The shipped page without executing it. `sim` is the simulation module -- the
   first `src` the page loads -- and `source` is everything the *workspace* is:
   every other script, inline and on disk, in document order. So a test can hold a
   rule to the whole workspace no matter which file it now lives in, while `sim`
   still names the one module the harness treats as the model. `scripts` is the
   load order as file names, which is what lets a test guard the split itself. */
function readSource() {
  const html = fs.readFileSync(HTML_PATH, 'utf8');
  const scripts = scriptsIn(html);
  const sim = (scripts.find(entry => entry.src) || {}).src || '';
  const workspace = scripts
    .filter(entry => entry.src !== sim)
    .map(entry => (entry.src ? readFile(entry.src) : entry.code));
  return { html, source: workspace.join('\n'), sim, scripts: scripts.map(entry => entry.src || 'index.html') };
}

/* The simulation's source, unexecuted -- so a test can hold the module to its
   boundary (no DOM, no clock, no stray globals) instead of trusting the header. */
function readSim() {
  const name = readSource().sim;
  if (!name) throw new Error('index.html loads no simulation module');
  return { name, code: readFile(name) };
}

/* The simulation as a loadable object, with no page and no DOM -- so a tool that
   only wants to run the model (measure.js) does not pay for the browser shim. The
   optional `transform(source)` patches it first, which is how the depth-cap sweep
   runs the same algorithm with one constant moved; it replaces the old trick of
   rewriting a script inlined in the page. */
function loadTornado(options = {}) {
  const source = readFile('tornado.js');
  const code = options.transform ? options.transform(source) : source;
  // a CommonJS module object, so the module's UMD takes its module.exports branch
  const module = { exports: {} };
  vm.runInNewContext(code, { module, exports: module.exports }, { filename: 'agent-tornado/tornado.js' });
  return module.exports;
}

/* Values returned from a vm context are proxies onto that realm: even
   Array.isArray() and .map() report the context's prototypes, so a copy built
   element-by-element in this realm is the only reliable conversion. Without it
   assert.deepEqual rejects values that are, field for field, identical. */
function toHost(value) {
  if (Array.isArray(value)) {
    const out = [];
    for (let index = 0; index < value.length; index++) out.push(toHost(value[index]));
    return out;
  }
  if (value && typeof value === 'object') {
    if (typeof value.then === 'function') return value;
    const out = {};
    for (const key of Object.keys(value)) out[key] = toHost(value[key]);
    return out;
  }
  return value;
}

/* A canvas context that answers any drawing call with a no-op, and hands back a
   real ImageData for createImageData so the dither pass runs for real. */
function context2d() {
  return new Proxy({}, {
    get(target, key) {
      if (key === 'createImageData') return (w, h) => ({ data: new Uint8ClampedArray(w * h * 4), width: w, height: h });
      if (key in target) return target[key];
      return () => {};
    },
    set(target, key, value) { target[key] = value; return true; }
  });
}

/* A DOM good enough that a real render, a real click and a real querySelector all
   behave the way they do in the browser. The markup in index.html is parsed into
   this tree, so getElementById is strict: a renamed or deleted id fails the suite
   instead of silently handing back a fresh empty node. */
let sharedParent = null;

const VOID_TAGS = new Set(['area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr']);

/* Inline style, with the CSSOM methods the app actually reaches for. */
function makeStyle() {
  const declared = {};
  return {
    _declared: declared,
    setProperty(name, value) { declared[name] = String(value); },
    getPropertyValue(name) { return declared[name] === undefined ? '' : declared[name]; },
    removeProperty(name) { const was = declared[name]; delete declared[name]; return was === undefined ? '' : was; }
  };
}

function makeNode(tag = 'div') {
  const node = {
    tagName: String(tag).toUpperCase(),
    id: '', value: '', checked: false,
    hidden: false, disabled: false, scrollTop: 0, title: '',
    width: 0, height: 0,
    style: makeStyle(), dataset: {}, children: [], childNodes: [],
    attrs: {}, _classes: new Set(),
    get classList() {
      const node = this;
      return {
        add(...names) { for (const name of names) node._classes.add(name); node.attrs.class = [...node._classes].join(' '); },
        remove(...names) { for (const name of names) node._classes.delete(name); node.attrs.class = [...node._classes].join(' '); },
        contains(name) { return node._classes.has(name); },
        toggle(name, force) {
          const on = force === undefined ? !node._classes.has(name) : Boolean(force);
          if (on) node._classes.add(name); else node._classes.delete(name);
          node.attrs.class = [...node._classes].join(' ');
          return on;
        }
      };
    },
    setAttribute(key, value) {
      const text = String(value);
      this.attrs[key] = text;
      if (key === 'class') for (const name of text.split(/\s+/)) if (name) this._classes.add(name);
    },
    getAttribute(key) { return this.attrs[key] === undefined ? null : this.attrs[key]; },
    hasAttribute(key) { return key in this.attrs; },
    // Handlers are recorded and dispatchable, so a test can drive a real click
    // through the same listener the app registered at boot.
    _listeners: {},
    addEventListener(type, fn) {
      (this._listeners[type] || (this._listeners[type] = [])).push(fn);
    },
    removeEventListener(type, fn) {
      const list = this._listeners[type];
      if (!list) return;
      const at = list.indexOf(fn);
      if (at >= 0) list.splice(at, 1);
    },
    dispatchEvent(event) {
      const type = typeof event === 'string' ? event : event.type;
      const payload = typeof event === 'string'
        ? { type, preventDefault() {}, stopPropagation() {} }
        : event;
      if (payload.preventDefault === undefined) payload.preventDefault = () => {};
      if (payload.stopPropagation === undefined) payload.stopPropagation = () => {};
      // A real event carries the node it fired on; handlers read event.target.
      if (payload.target === undefined || payload.target === null) payload.target = this;
      for (const fn of this._listeners[type] || []) fn(payload);
      return true;
    },
    getBoundingClientRect: () => ({ top: 0, left: 0, right: 0, bottom: 0, width: 0, height: 0 }),
    contains(other) {
      let walk = other && other.parentNode;
      while (walk) { if (walk === this) return true; walk = walk.parentNode; }
      return false;
    },
    focus() { this._focused = true; },
    blur() { this._focused = false; },
    click() { this.dispatchEvent({ type: 'click' }); },
    scrollTo: () => {},
    getContext: () => context2d(),
    querySelector(selector) {
      const found = findAll(this, selector);
      return found.length ? found[0] : null;
    },
    querySelectorAll(selector) { return findAll(this, selector); },
    // Text nodes belong in childNodes only, exactly as in the real DOM, because
    // firstChild/children are what clear() and the selectors depend on.
    append(...kids) {
      for (const kid of kids) {
        if (!kid) continue;
        kid.parentNode = this;
        this.childNodes.push(kid);
        if (kid.tagName !== 'TEXT') this.children.push(kid);
      }
    },
    appendChild(kid) { this.append(kid); return kid; },
    removeChild(kid) {
      const at = this.childNodes.indexOf(kid);
      if (at >= 0) this.childNodes.splice(at, 1);
      const elementAt = this.children.indexOf(kid);
      if (elementAt >= 0) this.children.splice(elementAt, 1);
      return kid;
    },
    remove() {
      if (this.parentNode) this.parentNode.removeChild(this);
    },
    replaceChildren(...kids) { this.children = []; this.childNodes = []; this.append(...kids); },
    insertBefore(kid) { this.append(kid); return kid; }
  };
  Object.defineProperty(node, 'className', {
    get() { return [...this._classes].join(' '); },
    set(value) {
      this._classes.clear();
      for (const name of String(value === undefined || value === null ? '' : value).split(/\s+/)) if (name) this._classes.add(name);
      this.attrs.class = [...this._classes].join(' ');
    }
  });
  // firstChild must be derived, since clear() loops on it.
  Object.defineProperty(node, 'firstChild', { get() { return this.childNodes[0] || null; } });
  // A real element's textContent is the concatenation of its subtree, and
  // asserting on a rendered row only works if this agrees with the browser.
  let ownText = '';
  Object.defineProperty(node, 'textContent', {
    get() { return ownText + this.childNodes.map(kid => kid.textContent || '').join(''); },
    set(value) {
      ownText = value === undefined || value === null ? '' : String(value);
      this.children.length = 0;
      this.childNodes.length = 0;
    }
  });
  // resize() measures the canvas's parent, and detached nodes have none.
  Object.defineProperty(node, 'parentElement', {
    get() { if (!sharedParent) sharedParent = makeNode('div'); return this.parentNode || sharedParent; }
  });
  Object.defineProperty(node, 'innerHTML', {
    get() { return ''; },
    set(value) { if (value === '') { this.children.length = 0; this.childNodes.length = 0; } }
  });
  return node;
}

/* --- a small selector engine, enough for everything the app queries -------- */

function matchesPart(node, part) {
  const nth = /:nth-child\((\d+)\)/.exec(part);
  const bare = part.replace(/:nth-child\(\d+\)/g, '');
  const attr = /\[([^\]=]+)(?:([~^$*|]?=)"?([^"\]]*)"?)?\]/.exec(bare);
  const id = /#([\w-]+)/.exec(bare);
  const classes = [...bare.matchAll(/\.([\w-]+)/g)].map(m => m[1]);
  const tag = /^([\w*-]+)/.exec(bare);

  if (tag && tag[1] !== '*' && node.tagName !== tag[1].toUpperCase()) return false;
  if (id && node.id !== id[1]) return false;
  for (const name of classes) if (!node._classes.has(name)) return false;
  if (attr) {
    const value = node.attrs[attr[1]];
    if (value === undefined) return false;
    if (attr[2]) {
      const wanted = attr[3];
      if (attr[2] === '=' && value !== wanted) return false;
      if (attr[2] === '^=' && !value.startsWith(wanted)) return false;
      if (attr[2] === '$=' && !value.endsWith(wanted)) return false;
      if (attr[2] === '*=' && !value.includes(wanted)) return false;
    }
  }
  if (nth) {
    const parent = node.parentNode;
    if (!parent) return false;
    if (parent.children.indexOf(node) !== Number(nth[1]) - 1) return false;
  }
  return Boolean(tag || id || classes.length || attr);
}

function descendants(node) {
  const out = [];
  const stack = [...node.children];
  while (stack.length) {
    const next = stack.shift();
    out.push(next);
    for (const kid of next.children) stack.push(kid);
  }
  return out;
}

function findAll(root, selector) {
  let current = [root];
  for (const part of String(selector).trim().split(/\s+/)) {
    const next = new Set();
    for (const start of current) {
      for (const node of descendants(start)) if (matchesPart(node, part)) next.add(node);
    }
    current = [...next];
    if (!current.length) break;
  }
  return current;
}

/* --- parse the shipped markup into that DOM ------------------------------- */

function decodeEntities(text) {
  return String(text)
    .replace(/&lt;/g, '<').replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"').replace(/&#39;/g, "'")
    .replace(/&nbsp;/g, ' ').replace(/&amp;/g, '&');
}

function applyAttributes(node, raw) {
  const pattern = /([^\s"'=<>`]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'=<>`]+)))?/g;
  let match;
  while ((match = pattern.exec(raw))) {
    const name = match[1].toLowerCase();
    const value = decodeEntities(match[2] ?? match[3] ?? match[4] ?? '');
    node.attrs[name] = value;
    if (name === 'id') node.id = value;
    else if (name === 'class') node.className = value;
    else if (name.startsWith('data-')) node.dataset[name.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase())] = value;
    else if (name === 'hidden') node.hidden = true;
    else if (name === 'checked') node.checked = true;
    else if (name === 'disabled') node.disabled = true;
    else if (name === 'value') node.value = value;
    else if (name === 'placeholder') node.placeholder = value;
    else if (name === 'type') node.type = value;
  }
}

function parseMarkup(html) {
  const source = html
    .replace(/<!doctype[^>]*>/i, '')
    .replace(/<!--[\s\S]*?-->/g, '')
    .replace(/(<style\b[^>]*>)[\s\S]*?(<\/style>)/gi, '$1$2')
    .replace(/(<script\b[^>]*>)[\s\S]*?(<\/script>)/gi, '$1$2');

  const root = makeNode('#document');
  const stack = [root];
  const ids = new Map();
  const tag = /<(\/?)([a-zA-Z][\w:-]*)((?:\s+[^\s"'=<>`]+(?:\s*=\s*(?:"[^"]*"|'[^']*'|[^\s"'=<>`]+))?)*)\s*(\/?)>/g;
  let cursor = 0;
  let match;
  while ((match = tag.exec(source))) {
    const text = source.slice(cursor, match.index);
    if (text.trim()) {
      const textNode = makeNode('text');
      textNode.textContent = decodeEntities(text.replace(/\s+/g, ' '));
      stack[stack.length - 1].append(textNode);
    }
    cursor = tag.lastIndex;
    const closing = match[1];
    const name = match[2].toLowerCase();
    if (closing) {
      for (let i = stack.length - 1; i > 0; i--) {
        if (stack[i].tagName === name.toUpperCase()) { stack.length = i; break; }
      }
      continue;
    }
    const node = makeNode(name);
    applyAttributes(node, match[3] || '');
    if (node.id && !ids.has(node.id)) ids.set(node.id, node);
    stack[stack.length - 1].append(node);
    if (!match[4] && !VOID_TAGS.has(name)) stack.push(node);
  }
  return { root, ids };
}

function makeContext(sources, html, options = {}) {
  const { root, ids } = parseMarkup(html);
  // Strict on purpose: a renamed or deleted id is a real defect, and resolving it
  // to a fresh empty node would hide exactly the bug this harness exists to catch.
  const byId = id => ids.get(id) || null;

  const documentNode = makeNode('#document');
  documentNode.getElementById = byId;
  documentNode.createElement = tagName => makeNode(tagName);
  documentNode.createTextNode = text => {
    const node = makeNode('text');
    node.textContent = text;
    return node;
  };
  documentNode.createDocumentFragment = () => makeNode('fragment');
  documentNode.querySelector = selector => root.querySelector(selector);
  documentNode.querySelectorAll = selector => root.querySelectorAll(selector);
  documentNode.documentElement = root.querySelector('html') || makeNode('html');
  documentNode.body = root.querySelector('body') || makeNode('body');
  documentNode.head = root.querySelector('head') || makeNode('head');
  documentNode.title = '';

  const windowListeners = {};
  const onWindow = (type, fn) => { (windowListeners[type] || (windowListeners[type] = [])).push(fn); };

  const context = {
    console, Math, JSON, Date, Promise, Set, Map, Array, Object, String, Number, Error, isNaN, parseInt, parseFloat,
    performance: { now: () => 0 },
    setTimeout: () => 0, clearTimeout: () => {},
    setInterval: () => 0, clearInterval: () => {},
    AbortController: class { constructor() { this.signal = {}; } abort() {} },
    // A test can stand a bridge in front of the page (`options.fetch`), which is
    // how a run that is saved, reloaded and resumed gets exercised for real.
    fetch: options.fetch || (() => Promise.reject(new Error('offline'))),
    requestAnimationFrame: () => 0,
    innerWidth: 1280, innerHeight: 800, devicePixelRatio: 1,
    addEventListener: onWindow,
    removeEventListener: (type, fn) => {
      const list = windowListeners[type];
      const at = list ? list.indexOf(fn) : -1;
      if (at >= 0) list.splice(at, 1);
    },
    dispatchEvent(event) {
      for (const fn of windowListeners[event.type] || []) fn(event);
      return true;
    },
    location: { protocol: 'http:', href: 'http://127.0.0.1:8799/' },
    navigator: { userAgent: 'node-harness' },
    document: documentNode
  };
  context.globalThis = context;
  vm.createContext(context);
  // document order, exactly as a browser would: the module first, then the page
  for (const script of sources) vm.runInContext(script.code, context, { filename: script.name });
  context.document = documentNode;
  return context;
}

/**
 * Load index.html into a headless context, as served: every script in order, which
 * is the workspace and, through it, the simulation. This is for the page tests
 * (markup, shortcuts, panels, the bridge); the model is tested without it, by
 * `require('./tornado.js')` or `loadTornado()`.
 */
function loadSim(options = {}) {
  const html = fs.readFileSync(HTML_PATH, 'utf8');
  const sources = scriptsIn(html).map(script => {
    if (!script.src) return { name: 'agent-tornado/index.html', code: script.code };
    return { name: `agent-tornado/${script.src}`, code: readFile(script.src) };
  });
  const context = makeContext(sources, html, options);
  const run = code => vm.runInContext(code, context);
  return {
    run,
    /* Dispatch on the real window, so a test can press a key the way a user does. */
    press(key, modifiers = {}) {
      const event = {
        type: 'keydown', key, target: context.document.body,
        metaKey: false, ctrlKey: false, shiftKey: false, altKey: false,
        preventDefault() {}, stopPropagation() {},
        ...modifiers
      };
      context.dispatchEvent(event);
      return event;
    },
    el: id => context.document.getElementById(id),
    build(brief, origin = 'test') {
      return run(`build(${JSON.stringify(brief)}, null, ${JSON.stringify(origin)})`);
    },
    step(epochs, dt = 1) {
      return run(`for (let i = 0; i < ${epochs}; i++) stepEpoch(${dt})`);
    },
    /* The run's own view of itself, converted into this realm so assert.deepEqual
       can compare it. The harness deliberately does not know what a snapshot is. */
    snapshot() {
      return toHost(run('tornado.snapshot()'));
    }
  };
}

module.exports = { loadSim, loadTornado, readSource, readSim, toHost };
