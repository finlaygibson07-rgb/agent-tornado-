#!/usr/bin/env node
/* fix.js -- the repair loop from a terminal, with no page in the way.
 *
 * The point of this file is that the loop can be finished, watched and judged
 * before a single pixel of UI exists, and can still be run when the window is not
 * open. It owns no decisions: the copy, the turns, the refusals and the stopping
 * rules are all loop.js. What lives here is the two adapters -- one to the bridge
 * that holds the hands, one to Ollama -- and the printing.
 *
 *   node fix.js --repo /Users/you/code/thing
 *   node fix.js --repo … --goal "make the tests pass" --suite run-suite
 *   node fix.js --repo … --model llama3.1:latest --turns 6 --diff
 *   node fix.js --repo … --yes      give the loop leave to write without asking
 *
 * Exit status: 0 when the suite ends green, 1 when it does not, 2 on bad usage.
 *
 * model.js is loaded here the same way sim-harness.js loads tornado.js: as a
 * script in a bare context, so the CLI and the page ask the model through one
 * client rather than two that will drift.
 */
'use strict';

const fs = require('node:fs');
const path = require('node:path');
const readline = require('node:readline');
const vm = require('node:vm');
const Loop = require('./loop.js');

const APP = __dirname;

const USAGE = `fix.js — repair a repo in a scratch copy

  node fix.js --repo <absolute path> [options]

  --repo <path>     the repository to copy and fix                (required)
  --goal <text>     what the loop is trying to achieve
  --suite <hand>    the test hand to run: run-suite | python-suite  (default run-suite)
  --model <name>    the Ollama model                                (default qwen2.5:14b)
  --bridge <url>    the bridge that holds the hands                 (default http://127.0.0.1:8800)
  --work <path>     the scratch root, $HOME allowed                 (default $HOME/Documents/agent-tornado/work)
  --turns <n>       model calls before the loop gives up            (default 12)
  --timeout <s>     seconds one model answer may take               (default 180)
  --diff            print the full patch when it stops
  --quiet           only the summary
  --yes             let the loop write in the copy and run what it wrote,
                    without asking (otherwise you are asked; with no terminal
                    to ask on, the run may read and test but not write)
  --token <token>   the bridge's token (default: read from .run/, or $TORNADO_TOKEN)
`;

function parse(argv) {
  const flags = { suite: 'run-suite', model: 'qwen2.5:14b', bridge: 'http://127.0.0.1:8800', work: Loop.WORK_ROOT };
  for (let i = 0; i < argv.length; i++) {
    const key = argv[i];
    const value = () => argv[++i];
    if (key === '--help' || key === '-h') flags.help = true;
    else if (key === '--diff') flags.diff = true;
    else if (key === '--quiet') flags.quiet = true;
    else if (key === '--yes' || key === '-y') flags.yes = true;
    else if (key === '--token') flags.token = value();
    else if (key === '--repo') flags.repo = value();
    else if (key === '--goal') flags.goal = value();
    else if (key === '--suite') flags.suite = value();
    else if (key === '--model') flags.model = value();
    else if (key === '--bridge') flags.bridge = value();
    else if (key === '--work') flags.work = value();
    else if (key === '--turns') flags.turns = Number(value());
    else if (key === '--timeout') flags.timeout = Number(value());
    else { throw new Error('unknown option: ' + key); }
  }
  return flags;
}

/* The bridge's token. The bridge writes it to its own 0600 record in .run/ when it
   starts, so the person who can read this folder can drive it, and nobody else. */
function bridgeToken(base, given) {
  if (given) return given;
  if (process.env.TORNADO_TOKEN) return process.env.TORNADO_TOKEN;
  let port = '';
  try { port = new URL(base).port; } catch (error) { return ''; }
  try {
    const record = JSON.parse(fs.readFileSync(path.join(APP, '.run', 'bridge-' + port + '.pid'), 'utf8'));
    return String(record.token || '');
  } catch (error) {
    return '';
  }
}

/* The one yes the loop needs, asked for before anything runs. */
async function askLeave(flags) {
  if (flags.yes) return true;
  if (!process.stdin.isTTY) return false;
  const prompt = readline.createInterface({ input: process.stdin, output: process.stdout });
  const answer = await new Promise(resolve => prompt.question(
    'Let the loop rewrite files in the scratch copy and run the suite on what it wrote?\n'
    + 'That runs code the model wrote, as you. Your repo is never written. [y/N] ', resolve));
  prompt.close();
  return /^y(es)?$/i.test(String(answer).trim());
}

/* The bridge's own record shape, so the loop cannot tell the CLI from the page. */
function bridgeTool(base, token) {
  return async function callTool(id, args, options) {
    const started = Date.now();
    let response;
    try {
      response = await fetch(base.replace(/\/+$/, '') + '/api/invoke', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Tornado-Token': token },
        body: JSON.stringify({ id, args, confirm: !!(options && options.confirm), dryRun: !!(options && options.dryRun) })
      });
    } catch (error) {
      return { ok: false, error: 'the bridge did not answer — is it running? (' + error.message + ')', ms: Date.now() - started };
    }
    const body = await response.json().catch(() => ({}));
    if (!response.ok) {
      return { ok: false, error: body.error || ('HTTP ' + response.status), status: response.status, ms: Date.now() - started };
    }
    return { ok: true, result: body.result, ms: body.ms != null ? body.ms : Date.now() - started };
  };
}

/* model.js, run in a bare context: the same client the page uses, with the two
   things it reaches for supplied. Nothing else of the page is loaded. */
function loadModelClient() {
  const code = fs.readFileSync(path.join(APP, 'model.js'), 'utf8');
  const context = vm.createContext({
    fetch, AbortController, setTimeout, clearTimeout,
    console, JSON, Date, Promise, Math, Object, Array, String, Number, Error
  });
  vm.runInContext(code, context, { filename: 'agent-tornado/model.js' });
  return {
    chatWithTools: (model, messages, tools, timeoutMs) => context.chatWithTools(model, messages, tools, timeoutMs)
  };
}

function describe(turn, index) {
  const head = String(index + 1).padStart(2, '0') + '  ' + turn.tool
    + (turn.hand ? ' → ' + turn.hand : '')
    + (typeof turn.exit === 'number' ? '  exit ' + turn.exit : '');
  const body = String(turn.output || '').trim();
  if (!body) return head;
  const lines = body.split('\n');
  const shown = lines.slice(0, 12).join('\n    ');
  return head + '\n    ' + shown + (lines.length > 12 ? `\n    … ${lines.length - 12} more lines` : '');
}

async function main() {
  let flags;
  try {
    flags = parse(process.argv.slice(2));
  } catch (error) {
    process.stderr.write(error.message + '\n\n' + USAGE);
    return 2;
  }
  if (flags.help || !flags.repo) {
    process.stdout.write(USAGE);
    return flags.help ? 0 : 2;
  }
  if (flags.repo.charAt(0) !== '/') {
    process.stderr.write('--repo must be an absolute path\n');
    return 2;
  }

  const base = flags.bridge.replace(/\/+$/, '');
  const token = bridgeToken(base, flags.token);
  const callTool = bridgeTool(base, token);

  /* Fail before the copy, not after it: a missing bridge or a missing suite hand
     would otherwise read as "the tests never passed", which is the wrong story. */
  let available = [];
  try {
    const response = await fetch(base + '/api/tools', { cache: 'no-store', headers: { 'X-Tornado-Token': token } });
    if (response.status === 401) {
      process.stderr.write('the bridge at ' + base + ' refused this token — it reads .run/bridge-<port>.pid in '
        + APP + '; pass --token, or set TORNADO_TOKEN\n');
      return 2;
    }
    if (!response.ok) throw new Error('HTTP ' + response.status);
    available = (await response.json()).tools || [];
  } catch (error) {
    process.stderr.write('the bridge is not answering at ' + base + ' (' + error.message + ')\n');
    process.stderr.write('start it with ./launch.command, or python3 hands.py --start --port 8800\n');
    return 2;
  }
  if (!available.some(tool => tool.id === flags.suite)) {
    process.stderr.write('no hand called ' + flags.suite + ' — installed: '
      + available.map(tool => tool.id).sort().join(', ') + '\n');
    return 2;
  }

  const consent = await askLeave(flags);
  const client = loadModelClient();
  const say = text => { if (!flags.quiet) process.stdout.write(text + '\n'); };

  const loop = Loop.createLoop({
    repo: flags.repo,
    goal: flags.goal || 'make the tests pass',
    suite: flags.suite,
    workRoot: flags.work,
    runId: new Date().toISOString().replace(/[:.]/g, '-'),
    maxTurns: flags.turns,
    consent,
    callTool,
    callModel: ({ messages, tools }) => client.chatWithTools(flags.model, messages, tools,
      flags.timeout > 0 ? flags.timeout * 1000 : undefined),
    onEvent: (kind, payload) => {
      if (kind === 'prepared') say('copy   ' + payload.work);
      // the delta is the summary's job, not a turn of its own
      else if (kind === 'turn' && payload.tool !== 'repo_delta') say('\n' + describe(payload, loop.turns.length - 1));
      else if (kind === 'finish') say('\nverdict ' + payload.outcome + ' — ' + payload.reason);
    }
  });

  say('repo   ' + flags.repo);
  say('suite  ' + flags.suite + ' · model ' + flags.model + ' · at most ' + (flags.turns || Loop.MAX_TURNS) + ' turns');
  say('leave  ' + (consent ? 'may write in the copy and test' : 'read and test only — no writes'));

  const result = await loop.run();

  if (flags.diff) {
    const patch = await loop.diff();
    process.stdout.write('\n' + (patch.output || '(no difference)') + '\n');
  }

  const changed = result.writes.length;
  process.stdout.write('\n' + [
    'outcome  ' + result.outcome,
    'reason   ' + result.reason,
    'copy     ' + (result.workDir || '(none)'),
    'writes   ' + changed + (changed ? ' — ' + result.writes.map(file => path.relative(result.workDir, file)).join(', ') : ''),
    'tests    ' + (result.tests ? 'exit ' + result.tests.exit : 'never ran'),
    'delta    ' + String((result.turns.filter(turn => turn.tool === 'repo_delta').pop() || {}).output || 'no changes')
      .trim().split('\n')[0]
  ].join('\n') + '\n');
  process.stdout.write('nothing was copied back — read the patch, then copy what you want\n');

  return result.outcome === 'green' ? 0 : 1;
}

main().then(code => process.exit(code)).catch(error => {
  process.stderr.write('fix.js failed: ' + (error && error.stack ? error.stack : error) + '\n');
  process.exit(1);
});
