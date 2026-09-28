/* panels.js -- the four panes and the transcript.
 *
 * Everything that turns workspace state into markup lives here: the task pane
 * (roots, the plan, the transcript), the crew list, the hands pane and the event
 * log, plus the tab switch that decides which is visible and the refresh that
 * rebuilds only what is stale. Nothing here decides what a step is worth or what
 * it runs -- it reads the run, the plan and the tools, and writes nodes.
 *
 * Loaded by index.html before the page's own script, exactly as tornado.js is.
 * What it needs from the page, read at call time: `tornado`, `plan`, `tools`,
 * `bridge`, `state`, `uiState`, `events`, `dirty`, `ui`, `el`, `$`, `clear`,
 * `select`, `followSelection`, `stamp`, `setStatus`, `logEvent`, `runBuild`,
 * `growComposer`, and from other modules `runPlan`, `proposePlan`.
 */
'use strict';

function setTab(name) {
  uiState.tab = name;
  for (const button of document.querySelectorAll('#tabs button')) {
    button.setAttribute('aria-selected', String(button.dataset.pane === name));
  }
  for (const pane of document.querySelectorAll('.pane')) {
    pane.classList.toggle('active', pane.id === 'pane-' + name);
  }
  dirty.crew = dirty.tools = dirty.log = dirty.plan = true;
  saveUi();
}

function renderRoots() {
  const node = $('roots');
  clear(node);
  const roots = tornado.agents.filter(a => a.depth === 0);
  if (!roots.length) { node.append(el('p', { class: 'note', text: 'no crew yet' })); return; }
  for (const root of roots) {
    const hands = root.hands.length ? root.hands.join(', ') : '—';
    node.append(el('div', { class: 'item' }, [
      el('span', { class: 'name', text: root.role }),
      el('span', { class: 'meta', text: hands })
    ]));
  }
}

function renderPlan() {
  const node = $('plan');
  clear(node);
  if (!plan.length) { node.append(el('p', { class: 'note', text: 'no plan yet' })); return; }
  plan.forEach((step, index) => {
    const tool = step.tool ? tools.get(step.tool) : null;
    const box = el('div', { class: 'step', 'data-state': step.state });
    box.append(el('header', null, [
      el('b', { text: String(index + 1).padStart(2, '0') + '  ' + step.clause.slice(0, 46) }),
      el('span', { class: 'meta', text: (tool ? tool.id : 'no hand')
        + (step.attempts ? ` · retried ${step.attempts}×` : '') })
    ]));
    if (tool) {
      const args = el('div', { class: 'args' });
      for (const [name, spec] of Object.entries(tool.args || {})) {
        const input = el('input', {
          value: step.args[name] ?? '',
          placeholder: spec.description || name,
          'aria-label': `${tool.id} ${name}`
        });
        input.addEventListener('input', () => {
          step.args[name] = input.value;
          // a value you typed over is yours, and no longer needs a second look
          if (step.proposed) step.proposed = step.proposed.filter(key => key !== name);
          dirty.plan = true;
          scheduleArgSave();
        });
        const fromModel = (step.proposed || []).includes(name);
        args.append(el('div', { class: 'arg' + (fromModel ? ' proposed' : '') }, [
          el('span', { text: name + (fromModel ? ' · model' : ''), title: fromModel ? 'proposed by the model — it asks before running' : '' }),
          input
        ]));
      }
      if (!Object.keys(tool.args || {}).length) {
        args.append(el('p', { class: 'note', text: 'this hand takes no arguments' }));
      }
      box.append(args);
      if (step.output) box.append(el('pre', { text: step.output }));
    } else {
      box.append(el('p', { class: 'note', text: 'no tool matched this clause — add one whose "matches" words appear in it' }));
    }
    node.append(box);
  });
}

function renderCrew(preserveScroll) {
  const node = $('crew-list');
  const keep = preserveScroll ? node.scrollTop : 0;
  const filter = ($('crew-filter').value || '').toLowerCase();
  const sort = $('crew-sort').value;
  let list = tornado.agents.slice();
  if (filter) list = list.filter(a => a.name.toLowerCase().includes(filter) || (a.role || '').toLowerCase().includes(filter));
  if (sort === 'fit') list.sort((a, b) => b.fit - a.fit);
  else if (sort === 'recent') list.sort((a, b) => b.id - a.id);
  else list.sort((a, b) => b.depth - a.depth || b.fit - a.fit);

  const total = list.length;
  list = list.slice(0, 160);
  uiState.filtered = list;
  clear(node);
  if (!list.length) { node.append(el('p', { class: 'note', text: 'no agents match' })); return; }
  for (const agent of list) {
    const bar = el('span', { class: 'bar' }, [el('i', { style: { width: Math.round(agent.fit * 100) + '%' } })]);
    const row = el('div', {
      class: 'item', role: 'button', tabindex: '0',
      'aria-selected': String(state.selected === agent)
    }, [
      el('span', { class: 'label', text: 'd' + agent.depth }),
      el('span', { class: 'name', text: agent.role }),
      bar,
      el('span', { class: 'meta', text: agent.fit.toFixed(2) })
    ]);
    row.addEventListener('click', () => { select(agent); followSelection(); });
    node.append(row);
  }
  if (total > list.length) {
    node.append(el('p', { class: 'note', text: `showing ${list.length} of ${total} — filter to narrow` }));
  }
  if (keep) node.scrollTop = keep;
}

function renderTools() {
  const node = $('tools');
  clear(node);
  for (const problem of tools.problems) {
    node.append(el('p', { class: 'note', text: `manifest problem in ${problem.file}: ${problem.error}` }));
  }
  if (!tools.list.length) {
    node.append(el('p', { class: 'note', text: bridge.online ? 'no tools installed yet — drop a manifest above' : '' }));
    return;
  }
  for (const tool of tools.list) {
    const row = el('div', { class: 'item' }, [
      el('span', { class: 'name', text: tool.name }),
      el('span', { class: 'meta', text: `${tool.kind}${tool.confirm ? ' · destructive' : ''}` })
    ]);
    row.addEventListener('click', () => runHandAlone(tool));
    node.append(row);
    if (tool.description) node.append(el('p', { class: 'note', text: tool.description }));
  }
}

/* Running a hand on its own, outside a plan, is the fastest way to find out
   what it does before you let a crew near it. */
function runHandAlone(tool) {
  setTab('hands');
  setStatus(`${tool.id}: fill the arguments in the plan, or use ⌘K → run hand`);
  const preview = JSON.stringify(Object.fromEntries(
    Object.entries(tool.args || {}).map(([name, spec]) => [name, spec.default ?? ''])
  ), null, 2);
  logEvent('hand', `${tool.id} selected — schema ${preview.replace(/\s+/g, ' ')}`);
}

function renderCalls() {
  const node = $('calls');
  clear(node);
  if (!tools.calls.length) { node.append(el('p', { class: 'note', text: 'nothing yet' })); return; }
  for (const call of tools.calls) {
    const head = el('div', { class: 'item' }, [
      el('span', { class: 'name', text: call.id }),
      el('span', { class: 'meta', text: `${call.ok ? 'ok' : 'failed'} · ${call.ms}ms` })
    ]);
    node.append(head);
    node.append(el('pre', { text: call.ok ? String(call.result?.output ?? '').slice(0, 4000) : call.error }));
  }
}

/* The transcript: builds this session actually ran. Click loads the wording back
   into the composer (nothing re-runs without you saying so); the row's build
   button reruns it deliberately. */
function renderRecent() {
  const node = $('recent');
  clear(node);
  if (!state.history.length) {
    node.append(el('p', { class: 'note', text: 'nothing built yet' }));
    return;
  }
  state.history.forEach((entry, index) => {
    // Two sibling controls, never a button inside a button -- a nested control is
    // invalid and gives a screen reader an ambiguous target.
    const recall = el('button', { type: 'button', class: 'recall', title: 'Load this wording into the composer' }, [
      el('span', { class: 'label mono', text: String(index + 1).padStart(2, '0') }),
      el('span', { class: 'name', text: entry.text })
    ]);
    recall.addEventListener('click', () => {
      ui.$prompt.value = entry.text;
      growComposer();
      ui.$prompt.focus();
      setStatus('loaded into the composer — enter to build');
    });
    const rerun = el('button', { type: 'button', class: 'ghost', title: 'Build this again', text: 'build' });
    rerun.addEventListener('click', () => runBuild(entry.text));
    node.append(el('div', { class: 'item' }, [
      recall,
      el('span', { class: 'meta', text: `${entry.count} · ${entry.source}` }),
      rerun
    ]));
  });
}

/* The runs on disk, newest first. The one you are on is marked rather than
   offered, and every other one opens in place of it. */
function renderRuns() {
  const node = $('runs');
  clear(node);
  if (!savedRuns.length) {
    node.append(el('p', { class: 'note', text: bridge.online ? 'no saved runs yet' : 'saved runs need the bridge' }));
    return;
  }
  for (const run of savedRuns) {
    const current = run.id === runId;
    const when = run.at ? stamp(Date.parse(run.at)) : '';
    const brief = (run.brief || '(cleared)').split('\n')[0];
    const row = [
      el('span', { class: 'name', text: brief, title: run.brief || '' }),
      el('span', { class: 'meta', text: `${run.settled}/${run.steps} · ${run.done ? 'done' : 'owed'}${when ? ' · ' + when : ''}` })
    ];
    if (current) row.push(el('span', { class: 'meta', text: 'current' }));
    else {
      const open = el('button', { type: 'button', class: 'ghost', text: 'open', title: 'Open this run in place of the current one' });
      open.addEventListener('click', () => openRun(run.id));
      row.push(open);
    }
    node.append(el('div', { class: 'item', 'data-run': run.id }, row));
  }
}

function renderLog() {
  const node = $('events');
  clear(node);
  if (!events.length) { node.append(el('p', { class: 'note', text: 'nothing yet' })); return; }
  for (const event of events.slice(0, 200)) {
    node.append(el('div', { class: 'item' }, [
      el('span', { class: 'label', text: event.kind }),
      el('span', { class: 'name', text: event.text }),
      el('span', { class: 'meta', text: stamp(event.at) })
    ]));
  }
}

/* Rebuild only what is visible and stale. The crew list is refreshed on a slow
   cadence from the tick loop instead of unconditionally, because rebuilding 160
   rows every frame would reset hover state under the pointer. */

function refreshPanels(preserveScroll) {
  if (dirty.roots) { renderRoots(); dirty.roots = false; }
  if (dirty.plan && uiState.tab === 'task') { renderPlan(); dirty.plan = false; }
  if (dirty.crew && uiState.tab === 'crew') { renderCrew(preserveScroll); dirty.crew = false; }
  if (dirty.tools && uiState.tab === 'hands') { renderTools(); dirty.tools = false; }
  if (dirty.calls && uiState.tab === 'hands') { renderCalls(); dirty.calls = false; }
  if (dirty.log && uiState.tab === 'log') { renderLog(); dirty.log = false; }
  if (dirty.recent && uiState.tab === 'task') { renderRecent(); dirty.recent = false; }
  if (dirty.runs && uiState.tab === 'task') { renderRuns(); dirty.runs = false; }
}
