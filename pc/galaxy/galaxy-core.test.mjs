// node --test pc/galaxy/galaxy-core.test.mjs   (also run by tests/run_tests.py when node is installed)
import test from "node:test";
import assert from "node:assert/strict";
import * as G from "./galaxy-core.js";

test("every state defines every parameter", () => {
  const keys = Object.keys(G.STATES.idle).sort();
  for (const s of G.STATE_NAMES) assert.deepEqual(Object.keys(G.STATES[s]).sort(), keys, s);
  assert.deepEqual(G.STATE_NAMES, ["idle", "arming", "listening", "processing", "speaking", "error"]);
  for (const s of G.STATE_NAMES) assert.ok(G.STATE_LABELS[s], s);
});

test("easing is frame-rate independent: 60 small steps == 30 double steps", () => {
  let a = 0, b = 0;
  for (let i = 0; i < 60; i++) a = G.ease(a, 1, 0.08, 1 / 60);
  for (let i = 0; i < 30; i++) b = G.ease(b, 1, 0.08, 1 / 30);
  assert.ok(Math.abs(a - b) < 1e-9, `${a} vs ${b}`);
  assert.ok(a > 0.99 && a < 1, "moves most of the way within a second, never overshoots");
  const p = G.easeParams({ color: [0, 0, 0], glow: 0 }, { color: [1, 1, 1], glow: 1 }, 0.5, 1 / 60);
  assert.equal(p.glow, 0.5); assert.deepEqual(p.color, [0.5, 0.5, 0.5]);
});

test("audio levels: voice = bins 10-60%, bass = first 6, treble = 65%+", () => {
  const bins = new Uint8Array(100);
  for (let i = 0; i < 6; i++) bins[i] = 255;            // bass only
  let l = G.audioLevels(bins);
  assert.equal(l.bass, 1); assert.equal(l.voice, 0); assert.equal(l.treble, 0);
  bins.fill(0); for (let i = 10; i < 60; i++) bins[i] = 102;   // 40% in the voice band
  l = G.audioLevels(bins, { gain: 2.4, floor: 0.05 });
  assert.ok(Math.abs(l.voice - Math.min(1, 0.4 * 2.4 + 0.05)) < 1e-9);
  assert.deepEqual(G.audioLevels(new Uint8Array(0)), { voice: 0, bass: 0, treble: 0 });
});

test("level smoothing: fast attack, slow decay", () => {
  const up = G.smoothLevel(0, 1, 1 / 60), down = 1 - G.smoothLevel(1, 0, 1 / 60);
  assert.ok(up > 0.4 && down < 0.1, `${up} ${down}`);
});

test("synthetic envelope is deterministic and in range", () => {
  for (let t = 0; t < 10; t += 0.137) {
    const a = G.syntheticLevel(t), b = G.syntheticLevel(t);
    assert.deepEqual(a, b);
    for (const v of Object.values(a)) assert.ok(v >= 0 && v <= 1);
  }
});

test("performance mode: 3 s under 45 fps switches on and stays on; manual overrides", () => {
  let st = { perf: false, slow: 0 };
  for (let i = 0; i < 89; i++) st = G.perfStep(st, 30, 1 / 30);
  assert.equal(st.perf, false, "not before 3 s");
  st = G.perfStep(st, 30, 2 / 30);
  assert.equal(st.perf, true);
  for (let i = 0; i < 300; i++) st = G.perfStep(st, 120, 1 / 120);
  assert.equal(st.perf, true, "no flapping back");
  let s2 = { perf: false, slow: 0 };
  for (let i = 0; i < 50; i++) s2 = G.perfStep(s2, 30, 1 / 30);
  s2 = G.perfStep(s2, 60, 1 / 60);
  assert.equal(s2.slow, 0, "a good frame resets the timer");
  assert.equal(G.perfStep({ perf: true }, 60, 0.016, "off").perf, false);
  assert.equal(G.perfStep({ perf: false }, 60, 0.016, "on").perf, true);
});

test("reduced motion slows a separate clock (continuous, no jump)", () => {
  assert.equal(G.advanceClock(10, 1, false), 11);
  assert.equal(G.advanceClock(10, 1, true), 10.25);
});

test("the sky is the real one: named constellations at their true positions, lines inside each figure", () => {
  const a = G.skyLayout(7), b = G.skyLayout(7);
  assert.deepEqual(a, b);                                                   // seeded: the same sky every load
  const names = new Set(G.CONSTELLATIONS.map(c => c.name));
  for (const n of ["Orion", "Ursa Major", "Cassiopeia", "Cygnus", "Scorpius", "Leo"]) assert.ok(names.has(n), n);
  const star = n => a.stars.find(s => s.name === n);
  const ang = (p, q) => Math.acos(p.reduce((s, v, i) => s + v * q[i], 0) / 1e4) * 180 / Math.PI;
  // real angular separations (degrees): Betelgeuse-Rigel ~18.6, Dubhe-Merak ~5.4 (the Pointers), Polaris at the pole
  assert.ok(Math.abs(ang(star("Betelgeuse").p, star("Rigel").p) - 18.6) < 0.6);
  assert.ok(Math.abs(ang(star("Dubhe").p, star("Merak").p) - 5.4) < 0.3);
  assert.ok(star("Polaris").p[1] > 99.9);
  assert.ok(star("Sirius").size > star("Mintaka").size, "brighter stars draw bigger");
  for (const [i, j] of a.lines) assert.equal(a.stars[i].con, a.stars[j].con, "a stick figure never jumps to another constellation");
  assert.ok(a.field.length > 1500 && a.galaxies.length >= 4);
  const p = G.skyLayout(7, true);
  assert.equal(p.stars.length, a.stars.length, "performance mode keeps every constellation");
  assert.ok(p.field.length < a.field.length);
});

test("orb displacement: barely ripples at rest, clamped when loud", () => {
  const rest = G.displacementScale(G.STATES.idle, 1.3, { voice: 0, bass: 0 });
  assert.ok(rest < 0.06, `${rest}`);
  const loud = G.displacementScale({ ...G.STATES.listening, amp: 5 }, 0, { voice: 1, bass: 1 });
  assert.equal(loud, 0.45);
});
