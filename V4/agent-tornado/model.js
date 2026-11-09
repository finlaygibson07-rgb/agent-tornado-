/* model.js -- the local model: the one place the workspace talks to Ollama.
 *
 * Three questions are ever put to it: how does this brief decompose, what should
 * these arguments be, and -- in the repair loop -- what should happen next. The
 * first two go through `askModel`, so there is one address, one timeout and one
 * way a reply is parsed; the third is `chatWithTools`, which is the same address
 * and the same timeout with a tool list attached. A second copy of the client is
 * how the two paths drifted apart before.
 *
 * The model never gets the last word on structure. The brief is parsed first and
 * the model may only add sub-steps under its leaves, so a typed outline survives
 * by construction -- asking a model to hand back the whole outline was tried, and
 * a live qwen2.5:14b promoted typed children to siblings. The refined tree goes
 * back out as indented text through the same `parseBrief` as any brief, so it is
 * held to the same budgets and depth cap, and a resumed run rebuilds the same
 * tree from its record with no model at all.
 *
 * Loaded by index.html after bridge.js and before plan.js. Needs `Tornado`.
 */
'use strict';

const MODEL_URL = 'http://127.0.0.1:11434/api/chat';
/* How long one answer may take. A 14B model on a laptop, with a dozen turns of
   transcript to read, regularly needs more than half a minute -- 30s aborted the
   first live repair run mid-job -- so the default is three minutes. */
const MODEL_TIMEOUT = 180000;

/* How many sub-steps the model may add under one leaf, and how many leaves it
   is shown. The typed outline is the plan; the model only fills in what a leaf
   left implicit. */
const MODEL_SPLIT = 5;
const MODEL_LEAVES = 32;

const EXPAND_SCHEMA = {
  type: 'object',
  properties: {
    expand: {
      type: 'array',
      items: {
        type: 'object',
        properties: { index: { type: 'integer' }, steps: { type: 'array', items: { type: 'string' } } },
        required: ['index', 'steps']
      }
    }
  },
  required: ['expand']
};

const PROPOSE_SCHEMA = {
  type: 'object',
  properties: {
    steps: {
      type: 'array',
      items: {
        type: 'object',
        properties: { index: { type: 'integer' }, args: { type: 'object' } },
        required: ['index', 'args']
      }
    }
  },
  required: ['steps']
};

/* One question, one JSON answer. The reply is constrained by `schema` where the
   installed Ollama understands one; an older Ollama refuses a schema with a 400,
   and is asked again for plain JSON rather than failing the build. Either way the
   caller validates the shape: a schema narrows a reply, it does not prove it. */
async function askModel(model, system, user, schema) {
  const ask = async format => {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), MODEL_TIMEOUT);
    try {
      return await fetch(MODEL_URL, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, signal: controller.signal,
        body: JSON.stringify({ model, stream: false, format, messages: [
          { role: 'system', content: system },
          { role: 'user', content: user }
        ] })
      });
    } finally {
      clearTimeout(timeout);
    }
  };
  let response = await ask(schema || 'json');
  if (schema && response.status === 400) response = await ask('json');
  if (!response.ok) throw new Error('Ollama HTTP ' + response.status);
  const payload = await response.json();
  const text = payload && payload.message ? payload.message.content : '';
  try {
    return JSON.parse(text || '{}');
  } catch (error) {
    throw new Error('Ollama replied with something that is not JSON');
  }
}

/* One turn of the repair loop: what should happen next, given everything that
   already happened. The reply is a tool call or a sentence, and both come back so
   the loop can decide -- this function does not choose, it only asks.

   No `format` here on purpose. A JSON schema and a tool call are two different
   constraints, and asking for both is how a model ends up answering in neither.
   Arguments arrive as an object from Ollama and as a JSON string from some
   models, so both are normalised before the loop sees them. */
async function chatWithTools(model, messages, tools, timeoutMs) {
  const limit = Number(timeoutMs) > 0 ? Number(timeoutMs) : MODEL_TIMEOUT;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), limit);
  let payload;
  try {
    const response = await fetch(MODEL_URL, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, signal: controller.signal,
      body: JSON.stringify({ model, stream: false, messages, tools })
    });
    if (!response.ok) throw new Error('Ollama HTTP ' + response.status);
    payload = await response.json();
  } catch (error) {
    // an abort says "This operation was aborted", which names nothing you can act on
    if (error && error.name === 'AbortError') {
      throw new Error(`the model took longer than ${Math.round(limit / 1000)}s to answer`);
    }
    throw error;
  } finally {
    clearTimeout(timeout);
  }
  const message = (payload && payload.message) || {};
  const calls = Array.isArray(message.tool_calls) ? message.tool_calls : [];
  return {
    content: String(message.content || ''),
    toolCalls: calls
      .map(call => ({
        name: String((call && call.function && call.function.name) || ''),
        args: asArguments(call && call.function ? call.function.arguments : null)
      }))
      .filter(call => call.name)
  };
}

function asArguments(raw) {
  if (!raw) return {};
  if (typeof raw === 'string') {
    try { return JSON.parse(raw); } catch (error) { return {}; }
  }
  return raw;
}

/* One model-written step as one clause. The outline grammar splits on `;`, `,`,
   `|` and on joining words, and a colon nests; the model does not know that, and
   "check the input and output values" must not come back as two siblings. So the
   model's text is flattened to the one clause it meant. Typed text never passes
   through here -- it was parsed already and stays exactly as written. */
function asOneClause(text) {
  return String(text ?? '')
    .replace(/\s+/g, ' ')
    .replace(/:/g, ' -')
    .replace(/\s*[;,|]\s*/g, ' ')
    .replace(/\s+(and then|then|and|next|plus)\s+/gi, ' & ')
    .replace(/^(and then|then|and|next|plus)\s+/i, '')
    .trim();
}

/* A tree back to the indented text a person would type. Parsing this gives the
   same tree back, which is what lets the record's brief rebuild the run with no
   model at all. */
function outlineFromTree(nodes, depth = 0, lines = []) {
  for (const node of nodes) {
    lines.push('  '.repeat(depth) + node.clause);
    outlineFromTree(node.children, depth + 1, lines);
  }
  return lines.join('\n');
}

/* The brief, refined by the model. The brief is parsed here first, so whatever
   structure you typed is the plan by construction: the model is shown only the
   leaves, and may only add sub-steps beneath one that clearly holds several
   actions. It can deepen the outline; it cannot flatten, reorder or reword it.
   Throws when the model had nothing to add, and the caller builds locally. */
async function decomposeBrief(text, model) {
  const tree = Tornado.parseBrief(text);
  const leaves = [];
  (function walk(nodes) {
    for (const node of nodes) node.children.length ? walk(node.children) : leaves.push(node);
  })(tree);
  const shown = leaves.slice(0, MODEL_LEAVES);
  const parsed = await askModel(model,
    'You refine a plan. You are shown its steps, numbered. For each step that clearly contains ' +
    `several distinct actions, list 2 to ${MODEL_SPLIT} concrete sub-steps in order. Leave simple steps out. ` +
    'Each sub-step is one short imperative action in plain words. Reply with JSON only: ' +
    '{"expand":[{"index":1,"steps":["..."]}]}.',
    shown.map((node, i) => `${i + 1}. ${node.clause}`).join('\n'), EXPAND_SCHEMA);
  let added = 0;
  for (const entry of Array.isArray(parsed && parsed.expand) ? parsed.expand : []) {
    const leaf = shown[Number(entry && entry.index) - 1];
    if (!leaf || leaf.children.length || !Array.isArray(entry.steps)) continue;
    const steps = entry.steps.map(asOneClause).filter(Boolean).slice(0, MODEL_SPLIT);
    if (steps.length < 2) continue;  // one sub-step is a rewording, not a split
    leaf.children = steps.map(clause => ({ clause, children: [] }));
    added += steps.length;
  }
  if (!added) throw new Error('the model had nothing to add');
  return outlineFromTree(tree);
}

/* Values for blank arguments. Only the reply is returned: deciding which values
   are allowed, and marking them as the model's rather than yours, is the plan's
   job, because the plan is what has to ask before running them. */
async function proposeArgs(model, steps) {
  const parsed = await askModel(model,
    'You fill in tool arguments. Reply with JSON only: {"steps":[{"index":0,"args":{...}}]}. ' +
    'Use absolute paths. Never invent an argument that is not in the schema. ' +
    'If you cannot know a value, omit that key.',
    JSON.stringify({ steps }), PROPOSE_SCHEMA);
  return Array.isArray(parsed && parsed.steps) ? parsed.steps : [];
}
