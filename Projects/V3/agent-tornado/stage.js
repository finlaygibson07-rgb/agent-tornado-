/* stage.js -- the canvas: the camera and the funnel.
 *
 * The funnel is laid out in "layout space" -- the size of the viewport at zoom 1
 * -- and the camera maps that to the screen. Keeping the projection here rather
 * than in the canvas transform is what lets the dither stay a fixed screen-space
 * grain at every zoom.
 *
 * This module owns the drawing and nothing else. It reads the run (`tornado`) and
 * the workspace's mutable state (`state`), and it writes to the canvas -- it never
 * decides what an agent is worth or when one spawns. Loaded by index.html before
 * the page's own script, exactly as tornado.js is, so there is one copy served to
 * the browser and to the headless harness.
 *
 * What it needs from the page, all read at call time rather than at load: `state`,
 * `ui`, `tornado`, `BAYER`, the `ctx`/`grain`/`grainCtx` canvases, and the pure
 * helpers `TAU`/`clamp`/`lerp`/`hash` re-exported by tornado.js.
 */
'use strict';

function toScreen(x, y) {
  return { x: x * state.view.z + state.view.x, y: y * state.view.z + state.view.y };
}
function toLayout(x, y) {
  return { x: (x - state.view.x) / state.view.z, y: (y - state.view.y) / state.view.z };
}

function zoomAt(screenX, screenY, factor) {
  const before = toLayout(screenX, screenY);
  state.view.z = clamp(state.view.z * factor, 0.35, 8);
  const after = toLayout(screenX, screenY);
  state.view.x += (after.x - before.x) * state.view.z;
  state.view.y += (after.y - before.y) * state.view.z;
  clampView();
}
function clampView() {
  const slackX = state.width * 0.9, slackY = state.height * 0.9;
  state.view.x = clamp(state.view.x, -slackX, slackX);
  state.view.y = clamp(state.view.y, -slackY, slackY);
}

function flowPoint(t, phase, lobe = 0) {
  const top = state.height * .10;
  const availableHeight = Math.max(180, state.height - 210);
  const radiusMax = Math.min(state.width * .38, availableHeight * .34);
  const taper = Math.pow(1 - t, 1.03);
  const lobePhase = phase + lobe * TAU / 3;
  const lean = Math.sin(state.time * .16 + t * 2.7 + lobePhase) * (14 + 34 * taper);
  const center = state.width * (.55 + .05 * Math.sin(lobePhase + state.time * .12));
  const radius = radiusMax * (.16 + .84 * taper) * (1 + .16 * Math.sin(lobePhase * 2.1 + t * 5));
  const angle = lobePhase + state.time * (.24 + t * t * 1.7) + t * TAU * (0.78 + .18 * Math.sin(lobePhase * 1.7));
  return {
    x: center + lean + Math.cos(angle) * radius + state.windX * (10 + t * 28),
    y: top + t * availableHeight + Math.sin(angle) * radius * (.18 + taper * .32) + state.windY * (8 + t * 22),
    radius
  };
}

function addGrain(x, y, amount) {
  const gx = Math.floor(x / state.grainScale), gy = Math.floor(y / state.grainScale);
  if (gx < 0 || gy < 0 || gx >= grain.width || gy >= grain.height) return;
  const index = gy * grain.width + gx;
  state.field[index] = Math.min(255, state.field[index] + amount);
}

function addStreamline(baseAngle, strength) {
  if (strength <= 0) return;
  for (let step = 0; step < 100; step++) {
    const t = step / 99;
    const p = flowPoint(t, baseAngle, Math.round(baseAngle / TAU * 3) % 3);
    const s = toScreen(p.x, p.y);
    addGrain(s.x, s.y, 120 * strength);
    addGrain(s.x + Math.sin(t * TAU * 2 + baseAngle) * 5, s.y, 70 * strength);
  }
}

function addEdge(from, to, ink) {
  for (let step = 1; step < 26; step++) {
    const t = step / 26, bend = Math.sin(t * Math.PI) * 18;
    addGrain(lerp(from.x, to.x, t) + bend, lerp(from.y, to.y, t), 170 * ink);
  }
}

function paint() {
  const image = grainCtx.createImageData(grain.width, grain.height);
  for (let i = 0; i < state.field.length; i++) {
    const level = state.field[i];
    const x = i % grain.width, y = Math.floor(i / grain.width);
    const on = level > 28 + BAYER[(x % 4) + (y % 4) * 4] * 11;
    const value = on ? level : 0;
    image.data[i * 4] = value; image.data[i * 4 + 1] = value;
    image.data[i * 4 + 2] = value; image.data[i * 4 + 3] = value;
  }
  grainCtx.putImageData(image, 0, 0);
  ctx.save();
  ctx.globalCompositeOperation = 'screen';
  ctx.globalAlpha = .2;
  ctx.filter = 'blur(7px)';
  ctx.drawImage(grain, 0, 0, state.width, state.height);
  ctx.restore();
  ctx.filter = 'none';
  ctx.imageSmoothingEnabled = false;
  ctx.globalAlpha = 1;
  ctx.drawImage(grain, 0, 0, state.width, state.height);
}

function render() {
  ctx.clearRect(0, 0, state.width, state.height);
  ctx.fillStyle = '#050506'; ctx.fillRect(0, 0, state.width, state.height);
  state.field.fill(0);
  // The wind is ambient, but it is the crew's wind: with no agents the canvas
  // stays near-black so the composer is unmistakably the loudest thing, and the
  // vortex builds as the crew does.
  const ambience = clamp(tornado.agents.length / 30, 0.14, 1);
  for (let i = 0; i < 34; i++) addStreamline(i / 34 * TAU, ambience);

  // The funnel *is* the ranking: fitness sets the radius, so raw agents ride the
  // wide mouth and refined ones sink to the tip. Depth then pulls a subagent in
  // toward the agent that spawned it, which is what makes the lineage legible.
  const agents = tornado.agents;
  const order = agents.slice().sort((a, b) => a.fit - b.fit);
  const total = order.length;
  const tOf = new Map();
  for (let i = 0; i < total; i++) tOf.set(order[i], total < 2 ? .5 : i / (total - 1));
  for (const agent of agents) agent._f = flowPoint(tOf.get(agent), agent.phase, agent.lobe);
  // creation order guarantees a parent is visited before its children, so the
  // pull is always toward an already-resolved parent. The pull weakens with depth
  // so a 20-deep lineage reads as a strand down the funnel instead of collapsing
  // every descendant onto its root.
  for (const agent of agents) {
    const f = agent._f;
    const pull = agent.parent && agent.parent._p ? .42 / (1 + agent.depth * 0.5) : 0;
    agent._p = pull
      ? { x: lerp(f.x, agent.parent._p.x, pull), y: lerp(f.y, agent.parent._p.y, pull) }
      : { x: f.x, y: f.y };
    const s = toScreen(agent._p.x, agent._p.y);
    agent.x = s.x; agent.y = s.y;
    agent.wx = agent._p.x; agent.wy = agent._p.y;
  }

  // A recursive crew can reach hundreds of nodes; without an ink governor the
  // dither saturates to solid white and the grain structure is lost.
  const ink = clamp(150 / Math.max(1, agents.length), .3, 1) * Math.min(1, state.view.z * 0.9);

  for (const agent of agents) {
    if (!agent.parent || !agent.parent._p) continue;
    addEdge({ x: agent.parent.x, y: agent.parent.y }, { x: agent.x, y: agent.y }, ink);
  }

  for (const agent of agents) {
    const deep = Math.min(agent.depth, 8);
    const grains = Math.max(5, Math.round(((agent.depth ? 16 : 26) - deep * 1.4) * Math.min(2.4, state.view.z)));
    const radius = Math.max(3, ((agent.depth ? 7 : 10) - deep * 0.7) * state.view.z);
    const power = (150 + agent.fit * 130) * (0.7 + agent.fit * 0.6) * ink;
    for (let n = 0; n < grains; n++) {
      const angle = hash(agent.seed + n) * TAU, distance = hash(agent.seed + n * 2.3) * radius;
      addGrain(agent.x + Math.cos(angle) * distance, agent.y + Math.sin(angle) * distance * .65, power);
    }
    if (state.selected === agent) {
      ctx.strokeStyle = '#e6e7e4';
      ctx.lineWidth = 1;
      ctx.strokeRect(Math.round(agent.x) - 9.5, Math.round(agent.y) - 9.5, 19, 19);
    }
  }

  paint();

  for (const agent of agents) {
    const split = Math.min(.8, Math.abs(state.windX) * .7 + Math.abs(state.windY) * .35);
    if (split > .02) {
      ctx.fillStyle = 'rgba(255,0,0,.35)'; ctx.fillRect(agent.x - split, agent.y, 1, 1);
      ctx.fillStyle = 'rgba(0,0,255,.35)'; ctx.fillRect(agent.x + split, agent.y, 1, 1);
    }
  }
  if (state.selected) ui.$selected.style.display = 'block';
  else ui.$selected.style.display = 'none';
}
