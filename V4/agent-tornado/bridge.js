/* bridge.js -- the hands: the registry of tools and the client that talks to them.
 *
 * The app runs perfectly well with no bridge; hands simply go offline. Everything
 * that reaches the machine goes through here, and nowhere else in the page does a
 * fetch to the bridge -- so there is one place to audit what the workspace can ask
 * for. The bridge itself is the security boundary (see README, "How the bridge
 * stays narrow"); this module is only the client side of it.
 *
 * Loaded by index.html before the page's own script, exactly as tornado.js is.
 * What it needs from the page, read at call time: `dirty`, `logEvent`, `el`,
 * `$`, and `BRIDGE_DEFAULT`.
 */
'use strict';

/* The bridge's own address, owned here rather than by the page: this module loads
   before index.html, so a constant it needs at load time cannot live there. */
const BRIDGE_DEFAULT = 'http://127.0.0.1:8799';

/* The bridge that served this page is the one to talk to. A bridge started on
   another port (TORNADO_PORT=8800) would otherwise serve a page that calls 8799,
   and the bridge only answers its own origin. Opened from disk, there is no
   origin to follow, so the default is the best guess. */
const BRIDGE_BASE = typeof location !== 'undefined' && /^https?:$/.test(location.protocol)
  ? location.origin : BRIDGE_DEFAULT;

/* The bridge's per-launch token. The launcher opens the window at
   `/#token=…`; the fragment is read once, kept in this tab's sessionStorage so a
   reload still has it, and wiped from the address bar. A fragment never reaches a
   server, so the token is not in any log -- and a page that was not opened by the
   launcher has no token, so the hands stay shut to it. */
const BRIDGE_TOKEN = (function () {
  try {
    const found = /(?:^#|&)token=([A-Za-z0-9_-]+)/.exec(location.hash || '');
    if (found) {
      sessionStorage.setItem('tornado-token', found[1]);
      history.replaceState(null, '', location.pathname + location.search);
      return found[1];
    }
    return sessionStorage.getItem('tornado-token') || '';
  } catch (error) {
    return '';  // no location, no storage: a page opened from disk, or the test harness
  }
})();

/* Every request to the bridge, with the token. The one place a header is added,
   so no route can be called without it by accident. */
function bridgeFetch(path, init = {}) {
  const headers = Object.assign({}, init.headers, BRIDGE_TOKEN ? { 'X-Tornado-Token': BRIDGE_TOKEN } : {});
  return fetch(`${bridge.base}${path}`, Object.assign({}, init, { headers }));
}

const bridge = {
  base: BRIDGE_BASE, online: false, locked: false, dir: '', dryRun: false, checked: 0,

  /* The saved run: the plan's step state, kept on disk so a killed window does
     not lose the task. Reading is best-effort -- no bridge, no saved run, and the
     app carries on -- and a save reports whether it landed rather than throwing,
     because a run must never die of a bookkeeping failure. */
  async loadRun(id) {
    try {
      const query = id ? `?id=${encodeURIComponent(id)}` : '';
      const response = await bridgeFetch(`/api/run${query}`, { cache: 'no-store' });
      if (!response.ok) throw new Error('HTTP ' + response.status);
      const body = await response.json();
      return body.record || null;
    } catch (error) {
      return null;
    }
  },

  /* Every saved run, newest first, as summaries. An offline bridge is an empty
     list, never an error: the list is a convenience on top of the run. */
  async listRuns() {
    try {
      const response = await bridgeFetch('/api/runs', { cache: 'no-store' });
      if (!response.ok) throw new Error('HTTP ' + response.status);
      const body = await response.json();
      return Array.isArray(body.runs) ? body.runs : [];
    } catch (error) {
      return [];
    }
  },

  async saveRun(record) {
    try {
      const response = await bridgeFetch('/api/run', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ record })
      });
      return response.ok;
    } catch (error) {
      return false;
    }
  }
};

const tools = {
  list: [],            // published manifests from the bridge
  problems: [],
  calls: [],           // recent invocations, newest first

  get(id) { return this.list.find(tool => tool.id === id); },

  async rescan() {
    try {
      const response = await bridgeFetch('/api/tools', { cache: 'no-store' });
      // 401 is a bridge that is up and does not know this window: say so,
      // rather than calling it offline and sending you to start a second one
      bridge.locked = response.status === 401;
      if (!response.ok) throw new Error('HTTP ' + response.status);
      const body = await response.json();
      this.list = body.tools || [];
      this.problems = body.problems || [];
      bridge.online = true;
      bridge.dryRun = !!body.dryRun;
      dirty.tools = true;
      updateHandsSummary();
      return true;
    } catch (error) {
      this.list = [];
      bridge.online = false;
      dirty.tools = true;
      updateHandsSummary();
      return false;
    }
  },

  async invoke(id, args, options = {}) {
    const started = Date.now();
    let record;
    let status;
    try {
      const response = await bridgeFetch('/api/invoke', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id, args, confirm: !!options.confirm, dryRun: !!options.dryRun })
      });
      status = response.status;
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(body.error || ('HTTP ' + response.status));
      record = { id, ok: true, ms: body.ms ?? (Date.now() - started), result: body.result, at: Date.now() };
    } catch (error) {
      // `status` is what lets the plan tell a refusal (the bridge answered and
      // said no) from a hiccup (nothing answered at all), which is the whole
      // difference between retrying a step and repeating a refusal.
      record = { id, ok: false, ms: Date.now() - started, error: error.message, status, at: Date.now() };
    }
    this.calls.unshift(record);
    if (this.calls.length > 40) this.calls.length = 40;
    dirty.calls = true;
    logEvent(record.ok ? 'hand' : 'error',
      `${id} ${record.ok ? 'ok' : 'failed'} in ${record.ms}ms${record.ok ? '' : ' — ' + record.error}`);
    return record;
  },

  async install(filename, content, overwrite) {
    const response = await bridgeFetch('/api/install', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ filename, content, overwrite: !!overwrite })
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body.error || ('HTTP ' + response.status));
    await this.rescan();
    return body;
  },

  async uninstall(filename) {
    const response = await bridgeFetch('/api/uninstall', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ filename, confirm: true })
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body.error || ('HTTP ' + response.status));
    await this.rescan();
    return body;
  }
};

async function bridgeHealth() {
  try {
    const response = await bridgeFetch('/api/health', { cache: 'no-store' });
    if (!response.ok) throw new Error('HTTP ' + response.status);
    const body = await response.json();
    bridge.online = true;
    bridge.dir = body.toolsDir;
    bridge.dryRun = !!body.dryRun;
    return body;
  } catch (error) {
    bridge.online = false;
    return null;
  }
}

/* Both the rail line and the pane header are written here rather than in
   renderTools(), which only runs when its tab is visible -- otherwise the header
   sits on "checking the bridge…" until you happen to look at it. */
function updateHandsSummary() {
  const rail = $('hands-summary');
  const pane = $('hands-status');
  clear(rail);
  clear(pane);
  if (bridge.online) {
    rail.append(
      el('b', { text: `${tools.list.length} tools` }),
      document.createTextNode(' ready · '),
      el('b', { text: 'online' })
    );
    if (bridge.dryRun) rail.append(document.createTextNode(' · DRY RUN'));
    // A full absolute path is unreadable inside a 380px pane, so the folder name
    // is shown and the real path is kept in the tooltip.
    const folder = (bridge.dir || 'tools').split(/[\\/]/).filter(Boolean).pop() || 'tools';
    const code = el('code', { text: `${folder}/`, title: bridge.dir || 'tools/' });
    pane.append(
      el('b', { text: 'bridge online' }),
      document.createTextNode(` · ${tools.list.length} tools in `),
      code,
      document.createTextNode(bridge.dryRun ? ' · DRY RUN' : '')
    );
  } else if (bridge.locked) {
    rail.append(
      el('b', { text: 'locked' }),
      document.createTextNode(' — open the app with '),
      el('code', { text: './launch.command' })
    );
    pane.append(
      el('b', { text: 'bridge locked' }),
      document.createTextNode(' — it is running, but this window does not have its token. Open the app with '),
      el('code', { text: './launch.command' }),
      document.createTextNode(' and the hands come back.')
    );
  } else {
    rail.append(
      el('b', { text: 'offline' }),
      document.createTextNode(' — start '),
      el('code', { text: 'python3 hands.py' })
    );
    pane.append(
      el('b', { text: 'bridge offline' }),
      document.createTextNode(' — run '),
      el('code', { text: 'python3 hands.py' }),
      document.createTextNode(' in this folder. The tornado works without it; only the hands need it.')
    );
  }
}
