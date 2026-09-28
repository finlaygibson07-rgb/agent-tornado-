/* plan.js -- the plan: the brief's leaves, their hands, running them, and the
 * record of what running them did.
 *
 * The plan is derived from the brief's tree, not from the live crew: the moment
 * you press build every step has its hand, so it can be proposed, dry-run and
 * executed while the crew is still growing to cover it. The crew catches up to
 * the plan, not the other way round.
 *
 * It owns three pieces of state -- `plan`, the id of the run recording it, and the
 * queue of saves that keeps it on disk -- and everything that reads, runs,
 * records or resumes a step lives here, so a change to what a step *is* lands in
 * one file. Each run gets its own record, so building the next task cannot cost
 * you the last one. Loaded by index.html before the page's own script, exactly as
 * tornado.js is.
 *
 * What it needs from the page, read at call time: `tornado`, `tools`, `bridge`,
 * `dirty`, `toast`, `setStatus`, `logEvent`, `currentModel`, `el`, `$`, `clear`,
 * `build`, `growComposer` and `ui`.
 */
'use strict';

let plan = [];
let runId = '';
let runSeq = 0;
let savedRuns = [];

/* A run's id is its start time, with a sequence number for the runs that begin in
   the same millisecond -- two runs must never be one file. Colons and the dot are
   replaced so the id is safe as a filename, and the fixed width is what makes the
   ids sort in the order the runs happened, which is how the bridge finds the
   newest record without looking at a single mtime. */
function newRunId() {
  runSeq += 1;
  return new Date().toISOString().replace(/[:.]/g, '-') + '-' + String(runSeq).padStart(4, '0');
}

/* A step that has settled: it has an outcome the rest of the run can build on.
   Anything else -- idle, running, or a failure you might now be able to fix by
   filling in an argument -- is still owed, which is what makes re-running a plan
   resume it instead of repeating it. */
const SETTLED = ['ok', 'skipped'];

/* How many times a step is tried again after a failure that might pass. Two is
   enough for a hiccup (a busy file, a bridge that just restarted) and small
   enough that a wedged hand ends the step quickly. There is no delay between the
   attempts: the bridge is on loopback, so waiting would only add dead time to a
   run that has already failed once, and every attempt is in the audit log.
   Added to the file's own budget sense: this is a bound, not a retry loop. */
const RETRY_LIMIT = 2;

/* How much of a step's output the record keeps. The pane shows all of it; the
   record keeps what tells you what happened, because a 64-leaf plan of full
   64 KiB outputs would not fit in one request to the bridge (MAX_BODY). */
const OUTPUT_KEEP = 2000;

/* A step that has not settled. What `runPlan` runs, what `done` means, and what
   a resumed run reports as still owed -- one predicate, so the readout and the
   work cannot disagree. A leaf with no hand is not work this run can do, so it
   never blocks the record. */
function pendingSteps() {
  return plan.filter(step => step.tool && !SETTLED.includes(step.state));
}

/* `saved` is the plan of a run being resumed. A saved step is only reused for the
   step that is actually the same one -- same clause, same position -- so a brief
   edited since the save cannot inherit a stranger's outcome, and only the
   arguments the hand still declares are taken back. */
function leavesOf(nodes, out = []) {
  for (const node of nodes) {
    if (node.children.length) leavesOf(node.children, out);
    else out.push(node);
  }
  return out;
}

function buildPlan(source, saved = null) {
  // a build starts a run; a resume carries on with the one it is resuming
  if (!Array.isArray(saved)) runId = newRunId();
  const byClause = new Map();
  for (const agent of tornado.agents) if (!byClause.has(agent.role)) byClause.set(agent.role, agent);
  plan = leavesOf(tornado.tree || []).map((node, index) => {
    const toolId = (node.hands && node.hands[0]) || null;
    const tool = toolId ? tools.get(toolId) : null;
    const args = {};
    if (tool) for (const [name, spec] of Object.entries(tool.args || {})) args[name] = spec.default ?? '';
    const before = Array.isArray(saved) && saved[index] && saved[index].clause === node.clause ? saved[index] : null;
    if (before) {
      for (const name of Object.keys(args)) if (before.args && name in before.args) args[name] = before.args[name];
    }
    const proposed = before && Array.isArray(before.proposed)
      ? before.proposed.filter(name => name in args) : [];
    const agent = byClause.get(node.clause);
    return {
      clause: node.clause,
      agent: agent ? agent.name : null,
      tool: toolId,
      args,
      proposed,
      state: before ? before.state : 'idle',
      attempts: before ? before.attempts || 0 : 0,
      output: before ? before.output || '' : ''
    };
  });
  dirty.plan = true;
  dirty.roots = true;
  logEvent('plan', plan.filter(step => step.tool).length + ' of ' + plan.length + ' leaves have a hand bound');
  persistRun().then(refreshSavedRuns);
}

/* The run's record and the run's report are the same object. What is saved to
   the bridge after every transition is what `exportRun` writes to a file, so a
   run you reloaded and a run you exported cannot describe themselves differently. */
function runRecord() {
  return {
    kind: 'agent-tornado-run', version: 1, id: runId, at: new Date().toISOString(),
    brief: tornado.brief, epoch: Math.round(tornado.epoch), stats: tornado.stats,
    roots: tornado.agents.filter(a => a.depth === 0).map(a => ({ role: a.role, hands: a.hands })),
    done: plan.length > 0 && pendingSteps().length === 0,
    plan: plan.map(step => ({
      clause: step.clause, tool: step.tool, args: step.args, proposed: step.proposed || [], state: step.state,
      attempts: step.attempts || 0, output: String(step.output || '').slice(0, OUTPUT_KEEP)
    }))
  };
}

/* Saves are queued one behind the other and never raced: the bridge answers on
   threads, so two saves in flight could land out of order and leave an older
   state on disk than the one the page is showing. Awaiting the chain is also how
   a caller knows a transition was written before the next one begins.

   A save that fails is never a run that fails. The bridge is a convenience here:
   without it the plan still runs, and you are told once that this run will not
   survive a reload. */
let saving = Promise.resolve();
let saveWarned = false;
function persistRun() {
  // nothing has been built, so there is no run to record
  if (!runId) return Promise.resolve(false);
  const record = runRecord();
  saving = saving.then(() => bridge.saveRun(record)).then(saved => {
    if (!saved && bridge.online && !saveWarned) {
      saveWarned = true;
      logEvent('error', 'the bridge would not take the run record — this run will not survive a reload');
    }
    return saved;
  });
  return saving;
}

/* Typing an argument is a change worth keeping, but not one save per keystroke:
   the last value typed is written half a second after you stop. */
let argSave = 0;
function scheduleArgSave() {
  clearTimeout(argSave);
  argSave = setTimeout(() => { persistRun().then(refreshSavedRuns); }, 500);
}

/* The runs on disk, for the list in the task pane. */
async function refreshSavedRuns() {
  savedRuns = await bridge.listRuns();
  dirty.runs = true;
}

/* Open a saved run by id. The run you are leaving is already on disk -- every
   transition was saved -- so switching loses nothing. */
async function openRun(id) {
  if (id === runId) { setStatus('that is the run you are on'); return null; }
  const record = await bridge.loadRun(id);
  if (!record) { toast('that run could not be read — it may have been pruned'); await refreshSavedRuns(); return null; }
  const resumed = await resumeRun(record);
  await refreshSavedRuns();
  return resumed;
}

/* Starting over starts a record, so the newest thing on disk is the cleared run.
   Without it a reload would read the run that is still there and bring back the
   one you just cleared. */
function clearSavedRun() {
  runId = newRunId();
  return persistRun();
}

/* Ask the local model to fill the blank arguments. It gets the tool schemas and
   the clause, and is told to answer with nothing but JSON; anything it gets
   wrong leaves the field blank for you to fill, which is the safe failure. */
async function proposePlan(model) {
  const usable = plan.filter(step => step.tool);
  if (!usable.length) { toast('no hands are bound — add a tool whose words match the clause'); return; }
  if (!bridge.online) { toast('the bridge is offline, so there is nothing to plan against'); return; }

  setStatus('asking the model to fill in arguments…', true);
  const schema = usable.map((step, index) => ({
    index,
    clause: step.clause,
    tool: step.tool,
    args: tools.get(step.tool)?.args || {}
  }));

  try {
    let filled = 0;
    for (const answer of await proposeArgs(model, schema)) {
      const step = usable[answer && answer.index];
      if (!step || !answer.args || typeof answer.args !== 'object') continue;
      const schemaFor = tools.get(step.tool)?.args || {};
      for (const [key, value] of Object.entries(answer.args)) {
        if (key in schemaFor && value !== null && value !== undefined && value !== '') {
          step.args[key] = typeof value === 'string' ? value : JSON.stringify(value);
          // the model's value, not yours: it runs only after you have read it
          if (!step.proposed.includes(key)) step.proposed.push(key);
          filled++;
        }
      }
    }
    setStatus(filled ? `model filled ${filled} argument${filled === 1 ? '' : 's'}` : 'the model did not offer usable values');
    logEvent('plan', `model proposed ${filled} argument value(s)`);
  } catch (error) {
    setStatus('propose failed — ' + error.message);
    logEvent('error', 'propose args failed: ' + error.message);
  } finally {
    dirty.plan = true;
    // proposed arguments are part of the run, so a reload must not lose them
    await persistRun();
  }
}

function missingArgs(step) {
  const schema = tools.get(step.tool)?.args || {};
  return Object.entries(schema)
    .filter(([name, spec]) => spec.required && !String(step.args[name] ?? '').trim())
    .map(([name]) => name);
}

/* Whether a failure is worth another try. A refusal is a decision the bridge
   made with all the facts -- a missing argument, a destructive hand with no yes,
   a rate limit -- and sending it again would only repeat the refusal. A 5xx is
   the bridge or the tool failing, and no status at all means nothing answered,
   which is the definition of the thing worth trying twice. */
function isTransient(record) {
  return record.status === undefined || record.status >= 500;
}

/* One step's hand, tried to the bound. Each retry is a transition, so it is
   written to the record before the next attempt: a run killed during a retry
   comes back knowing how many times this step has already been sent. */
async function invokeStep(step, dryRun, approved) {
  let record = null;
  for (let attempt = 0; attempt <= RETRY_LIMIT; attempt++) {
    if (attempt) {
      step.attempts = attempt;
      dirty.plan = true;
      setStatus(`retrying ${step.tool} (${attempt} of ${RETRY_LIMIT})…`, true);
      await persistRun();
    }
    // `confirm` is a yes a person gave. Sending it on every call would make the
    // bridge's own check for destructive hands a formality.
    record = await tools.invoke(step.tool, step.args, { confirm: approved && !dryRun, dryRun });
    if (record.ok || !isTransient(record)) break;
  }
  return record;
}

async function runPlan(dryRun) {
  if (!plan.length) { toast('no plan — build a crew first'); return; }
  if (!plan.some(step => step.tool)) { toast('no hands are bound'); return; }
  if (!bridge.online) { toast('the bridge is offline'); return; }
  const steps = pendingSteps();
  if (!steps.length) { toast('every step has already settled — build again to start over'); return; }

  let approveAll = false;
  setStatus(dryRun ? 'dry run…' : `executing the plan… ${steps.length} of ${plan.length} to go`, true);
  await persistRun();
  for (const step of steps) {
    const missing = missingArgs(step);
    if (missing.length) {
      step.state = 'error';
      step.output = `missing required argument(s): ${missing.join(', ')}`;
      dirty.plan = true;
      await persistRun();
      continue;
    }
    const tool = tools.get(step.tool);
    // A destructive hand asks, and so does any hand holding a value the model
    // chose that you have not since typed over yourself.
    const unread = (step.proposed || []).length > 0;
    let approved = approveAll;
    if (tool && (tool.confirm || unread) && !dryRun && !approveAll) {
      const answer = await confirmStep(step, tool);
      if (answer === 'skip') { step.state = 'skipped'; dirty.plan = true; await persistRun(); continue; }
      if (answer === 'all') approveAll = true;
      if (answer === 'stop') break;
      approved = true;
      step.proposed = [];
    }
    step.state = 'running';
    dirty.plan = true;
    await persistRun();
    const record = await invokeStep(step, dryRun, approved);
    // What the hand actually did is what the crew learns from. A dry run did
    // nothing, so it teaches nothing; a shell that exited non-zero failed, even
    // though the bridge answered 200.
    if (!dryRun) {
      const exited = record.ok && record.result && typeof record.result.exit === 'number' ? record.result.exit : 0;
      tornado.report(step.clause, {
        ok: record.ok && exited === 0, timeout: record.status === 504,
        ms: record.ms, attempts: step.attempts || 0
      });
      dirty.crew = true;
    }
    // a shell that exited non-zero answered, and failed: it is still owed
    const failedExit = record.ok && record.result && typeof record.result.exit === 'number' && record.result.exit !== 0;
    step.state = record.ok && !failedExit ? 'ok' : 'error';
    step.output = record.ok
      ? (record.result.dryRun ? 'plan: ' + JSON.stringify(record.result.plan) : (record.result.output ?? JSON.stringify(record.result)))
      : record.error;
    dirty.plan = true;
    await persistRun();
  }
  const left = pendingSteps().length;
  refreshSavedRuns();
  setStatus(dryRun ? 'dry run finished' : (left ? `plan stopped with ${left} step${left === 1 ? '' : 's'} still owed — execute again to resume` : 'plan finished'));
  dirty.log = true;
}

/* A reload is where a long run used to die. The bridge has the last state it was
   told, so the brief goes back into the composer, the crew is rebuilt from it,
   and the plan comes back with the states it had. A step that was mid-flight
   when the page died is set back to idle: nothing is running now, and saying
   otherwise would stop that step from ever being tried again. */
async function resumeRun(given = null) {
  const record = given || await bridge.loadRun();
  if (!record || !record.brief || !Array.isArray(record.plan) || !record.plan.length) return null;

  // the run keeps its own id, so continuing it writes its own file and not a new
  // one; a record from anywhere else gets an id of its own
  runId = record.id || newRunId();
  if (ui.$prompt) ui.$prompt.value = record.brief;
  if (typeof growComposer === 'function') growComposer();
  build(record.brief, null, 'resumed', record.plan);
  const interrupted = plan.filter(step => step.state === 'running').length;
  for (const step of plan) if (step.state === 'running') step.state = 'idle';
  const left = pendingSteps().length;
  const first = plan.findIndex(step => step.tool && !SETTLED.includes(step.state));
  setStatus(left
    ? `resumed at step ${first + 1} · ${left} of ${plan.length} still owed · the brief is walked, the frontier is earned`
    : `a finished run was reloaded — ${plan.length} steps, all settled`);
  logEvent('run', `resumed a saved run — ${plan.length} steps, ${left} still owed`
    + (interrupted ? `, ${interrupted} interrupted mid-step` : ''));
  dirty.plan = true;
  // the disk should agree with the screen: nothing is running now
  await persistRun();
  return record;
}

/* A destructive hand never fires without an explicit yes, and neither does a
   value the model proposed. The yes is always for something you can read first,
   and the values the model chose are named, so you know which ones to check. */
function confirmStep(step, tool) {
  const proposed = step.proposed || [];
  return new Promise(resolve => {
    $('modal-title').textContent = tool.confirm ? 'Destructive hand' : 'Model-proposed arguments';
    clear($('modal-body'));
    $('modal-body').append(
      el('p', { text: tool.confirm
        ? `${tool.name} (${tool.id}) is flagged destructive.`
        : `${tool.name} (${tool.id}) would run with values the model chose.` }),
      ...(proposed.length ? [el('p', { text: `chosen by the model: ${proposed.join(', ')}` })] : []),
      el('p', { text: step.clause }),
      el('pre', { text: JSON.stringify(step.args, null, 2) })
    );
    const actions = $('modal-actions');
    clear(actions);
    const done = value => { $('modal').classList.remove('open'); resolve(value); };
    actions.append(
      el('button', { class: 'danger', text: 'run it', type: 'button', onclick: () => done('run') }),
      el('button', { text: 'skip', type: 'button', onclick: () => done('skip') }),
      el('button', { text: 'run all remaining', type: 'button', onclick: () => done('all') }),
      el('button', { text: 'stop', type: 'button', onclick: () => done('stop') })
    );
    $('modal').classList.add('open');
  });
}
