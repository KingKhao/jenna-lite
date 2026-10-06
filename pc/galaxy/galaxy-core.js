// Jenna's galaxy - the pure part. No WebGL here: the state table, easing, audio levels, the performance-mode
// decision and the seeded layout are plain functions with unit tests (galaxy-core.test.mjs). The three.js
// engine (galaxy.js) only draws numbers these functions already computed.

// ---------------- the state table: every visual parameter for every state, in one place ----------------
// Colours are linear-ish RGB 0..1. FORGE is the resting accent (a deep green-teal).
export const FORGE = [0.16, 0.72, 0.52];
export const STATES = {
  idle:       { color: FORGE,              color2: [0.10, 0.45, 0.42], opacity: 0.55, fresnel: 2.6, noiseSpeed: 0.18,
                amp: 0.35, glow: 0.35, rot: 0.05, rings: 0.0, base: 0.012, cycle: 0 },
  arming:     { color: [0.72, 0.30, 0.10], color2: [0.45, 0.16, 0.06], opacity: 0.50, fresnel: 2.4, noiseSpeed: 0.22,
                amp: 0.30, glow: 0.30, rot: 0.04, rings: 0.0, base: 0.012, cycle: 0 },
  listening:  { color: [1.00, 0.76, 0.24], color2: [1.00, 0.56, 0.12], opacity: 0.85, fresnel: 2.0, noiseSpeed: 0.55,
                amp: 1.00, glow: 0.85, rot: 0.08, rings: 0.0, base: 0.02, cycle: 0 },
  processing: { color: [0.20, 0.80, 0.70], color2: [0.62, 0.36, 0.95], opacity: 0.72, fresnel: 2.2, noiseSpeed: 0.45,
                amp: 0.55, glow: 0.60, rot: 0.22, rings: 0.85, base: 0.02, cycle: 1 },
  speaking:   { color: [0.30, 0.95, 0.78], color2: [0.18, 0.62, 0.95], opacity: 0.85, fresnel: 2.0, noiseSpeed: 0.50,
                amp: 0.90, glow: 0.90, rot: 0.10, rings: 0.15, base: 0.02, cycle: 0 },
  error:      { color: [0.95, 0.22, 0.20], color2: [0.55, 0.08, 0.08], opacity: 0.75, fresnel: 3.6, noiseSpeed: 0.02,
                amp: 0.05, glow: 0.40, rot: 0.0, rings: 0.0, base: 0.004, cycle: 0 },
};
export const STATE_NAMES = Object.keys(STATES);
export const STATE_LABELS = { idle: "Jenna is idle", arming: "Waiting for the microphone", listening: "Listening",
  processing: "Thinking", speaking: "Speaking", error: "Something went wrong" };

// ---------------- frame-rate independent easing ----------------
// Cover `rate` of the remaining distance per 1/60 s, scaled by the time that actually passed: 60 steps of
// 1/60 s and 30 steps of 1/30 s land in the same place.
export function ease(current, target, rate, dt) {
  const k = 1 - Math.pow(1 - rate, dt * 60);
  return current + (target - current) * k;
}

export function easeParams(cur, target, rate, dt) {
  const out = {};
  for (const key of Object.keys(target)) {
    const t = target[key], c = cur[key] ?? t;
    out[key] = Array.isArray(t) ? t.map((v, i) => ease(c[i], v, rate, dt)) : ease(c, t, rate, dt);
  }
  return out;
}

// ---------------- audio ----------------
// Frequency bins (0..255) -> {voice, bass, treble} 0..1. voice = average of bins 10-60%, bass = the first 6 bins,
// treble = 65% and up. The mic is boosted ~x2.4 with a small floor so the orb never looks dead between syllables.
export function audioLevels(bins, { gain = 1, floor = 0 } = {}) {
  const n = bins.length;
  if (!n) return { voice: 0, bass: 0, treble: 0 };
  const avg = (a, b) => { let s = 0, c = 0; for (let i = a; i < b; i++) { s += bins[i]; c++; } return c ? s / c / 255 : 0; };
  const clamp = v => Math.min(1, Math.max(0, v));
  const voice = avg(Math.floor(n * 0.10), Math.ceil(n * 0.60));
  return { voice: clamp(voice * gain + (voice > 0.01 ? floor : 0)), bass: clamp(avg(0, Math.min(6, n)) * gain),
           treble: clamp(avg(Math.floor(n * 0.65), n) * gain) };
}

// Fast attack, slow decay, frame-rate independent: breathes instead of twitching.
export function smoothLevel(prev, next, dt, attack = 0.45, decay = 0.08) {
  return ease(prev, next, next > prev ? attack : decay, dt);
}

// Deterministic speech-like envelope for when there's no real audio (syllables ~5/s, phrases ~every 2.4 s).
export function syntheticLevel(t) {
  const syll = Math.max(0, Math.sin(t * 2 * Math.PI * 4.8) * 0.5 + 0.5) ** 1.5;
  const phrase = Math.max(0, Math.sin(t * 2 * Math.PI / 2.4) * 0.6 + 0.4);
  const wobble = 0.85 + 0.15 * Math.sin(t * 7.3 + 1.1);
  const v = Math.min(1, syll * phrase * wobble);
  return { voice: v, bass: v * 0.7 * (0.6 + 0.4 * Math.sin(t * 3.1)), treble: v * 0.4 };
}

// ---------------- performance mode ----------------
// Under 45 fps for 3 s straight -> performance mode, and it stays on (no flapping). mode: "auto" | "on" | "off".
export function perfStep(st, fps, dt, mode = "auto") {
  if (mode === "on") return { ...st, perf: true };
  if (mode === "off") return { ...st, perf: false, slow: 0 };
  if (st.perf) return st;
  const slow = fps < 45 ? (st.slow || 0) + dt : 0;
  return { perf: slow >= 3, slow };
}

// ---------------- reduced motion: a separate, slower animation clock ----------------
// Multiplying time would make every phase jump when the setting flips; advancing a clock slower doesn't.
export function advanceClock(clock, dt, reduced) {
  return clock + dt * (reduced ? 0.25 : 1);
}

// ---------------- seeded randomness (the faint starfield and galaxies) ----------------
export function rng(seed) {   // mulberry32
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6D2B79F5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// ---------------- the real sky (2026-10-05) ----------------
// Real constellations instead of random glowing dots. The random
// clusters are gone. These are real stars: J2000 right ascension (hours) / declination (degrees), apparent
// magnitude, and a colour from the star's spectral class. Lines are the traditional stick figures.
// [name, raHours, decDeg, magnitude, colour]
const W = [0.80, 0.86, 1.00], B = [0.66, 0.78, 1.00], Y = [1.00, 0.93, 0.80], O = [1.00, 0.72, 0.46], R = [1.00, 0.55, 0.38];
export const CONSTELLATIONS = [
  { name: "Orion", stars: [["Betelgeuse", 5.919, 7.41, 0.5, R], ["Rigel", 5.242, -8.20, 0.1, B], ["Bellatrix", 5.419, 6.35, 1.6, B],
      ["Saiph", 5.796, -9.67, 2.1, B], ["Alnitak", 5.679, -1.94, 1.8, B], ["Alnilam", 5.604, -1.20, 1.7, B],
      ["Mintaka", 5.533, -0.30, 2.2, B], ["Meissa", 5.585, 9.93, 3.4, B]],
    lines: [[7, 0], [7, 2], [0, 4], [2, 6], [6, 5], [5, 4], [4, 3], [6, 1], [0, 2]] },
  { name: "Taurus", stars: [["Aldebaran", 4.599, 16.51, 0.9, O], ["Elnath", 5.438, 28.61, 1.7, B], ["Tianguan", 5.627, 21.14, 3.0, B],
      ["Theta Tauri", 4.478, 15.87, 3.4, W], ["Prima Hyadum", 4.330, 15.63, 3.6, Y], ["Secunda Hyadum", 4.382, 17.54, 3.8, Y],
      ["Ain", 4.477, 19.18, 3.5, Y]],
    lines: [[2, 0], [0, 3], [3, 4], [4, 5], [5, 6], [6, 1]] },
  { name: "Pleiades", stars: [["Alcyone", 3.791, 24.11, 2.9, B], ["Atlas", 3.819, 24.05, 3.6, B], ["Electra", 3.747, 24.11, 3.7, B],
      ["Maia", 3.763, 24.37, 3.9, B], ["Merope", 3.772, 23.95, 4.2, B], ["Taygeta", 3.754, 24.47, 4.3, B], ["Pleione", 3.819, 24.14, 5.0, B]],
    lines: [] },
  { name: "Gemini", stars: [["Castor", 7.577, 31.89, 1.6, W], ["Pollux", 7.755, 28.03, 1.1, O], ["Alhena", 6.629, 16.40, 1.9, W],
      ["Mebsuta", 6.732, 25.13, 3.0, Y], ["Wasat", 7.335, 21.98, 3.5, Y], ["Tejat", 6.383, 22.51, 2.9, R], ["Mekbuda", 7.068, 20.57, 3.8, Y]],
    lines: [[0, 3], [3, 5], [1, 4], [4, 6], [6, 2], [0, 1]] },
  { name: "Canis Major", stars: [["Sirius", 6.752, -16.72, -1.46, W], ["Mirzam", 6.378, -17.96, 2.0, B], ["Adhara", 6.977, -28.97, 1.5, B],
      ["Wezen", 7.140, -26.39, 1.8, Y], ["Aludra", 7.402, -29.30, 2.4, B], ["Furud", 6.338, -30.06, 3.0, B]],
    lines: [[1, 0], [0, 3], [3, 4], [3, 2], [2, 5]] },
  { name: "Ursa Major", stars: [["Dubhe", 11.062, 61.75, 1.8, O], ["Merak", 11.031, 56.38, 2.4, W], ["Phecda", 11.897, 53.69, 2.4, W],
      ["Megrez", 12.257, 57.03, 3.3, W], ["Alioth", 12.900, 55.96, 1.8, W], ["Mizar", 13.399, 54.93, 2.2, W], ["Alkaid", 13.792, 49.31, 1.9, B]],
    lines: [[0, 1], [1, 2], [2, 3], [3, 0], [3, 4], [4, 5], [5, 6]] },
  { name: "Ursa Minor", stars: [["Polaris", 2.530, 89.26, 2.0, Y], ["Kochab", 14.845, 74.16, 2.1, O], ["Pherkad", 15.345, 71.83, 3.0, W],
      ["Yildun", 17.537, 86.59, 4.4, W], ["Epsilon UMi", 16.766, 82.04, 4.2, Y], ["Zeta UMi", 15.734, 77.79, 4.3, W], ["Eta UMi", 16.292, 75.76, 5.0, W]],
    lines: [[0, 3], [3, 4], [4, 5], [5, 1], [1, 2], [2, 6], [6, 5]] },
  { name: "Cassiopeia", stars: [["Caph", 0.153, 59.15, 2.3, Y], ["Schedar", 0.675, 56.54, 2.2, O], ["Gamma Cas", 0.945, 60.72, 2.2, B],
      ["Ruchbah", 1.430, 60.24, 2.7, W], ["Segin", 1.907, 63.67, 3.4, B]],
    lines: [[0, 1], [1, 2], [2, 3], [3, 4]] },
  { name: "Cygnus", stars: [["Deneb", 20.690, 45.28, 1.25, W], ["Sadr", 20.370, 40.26, 2.2, Y], ["Albireo", 19.512, 27.96, 3.1, O],
      ["Aljanah", 20.770, 33.97, 2.5, O], ["Fawaris", 19.750, 45.13, 2.9, B]],
    lines: [[0, 1], [1, 2], [4, 1], [1, 3]] },
  { name: "Lyra", stars: [["Vega", 18.616, 38.78, 0.0, W], ["Sheliak", 18.835, 33.36, 3.5, B], ["Sulafat", 18.982, 32.69, 3.3, B],
      ["Zeta Lyrae", 18.746, 37.61, 4.3, W], ["Delta Lyrae", 18.908, 36.90, 4.3, R]],
    lines: [[0, 3], [3, 4], [4, 2], [2, 1], [1, 3]] },
  { name: "Aquila", stars: [["Altair", 19.846, 8.87, 0.8, W], ["Tarazed", 19.771, 10.61, 2.7, O], ["Alshain", 19.922, 6.41, 3.7, Y]],
    lines: [[1, 0], [0, 2]] },
  { name: "Scorpius", stars: [["Antares", 16.490, -26.43, 1.0, R], ["Dschubba", 16.006, -22.62, 2.3, B], ["Acrab", 16.091, -19.81, 2.6, B],
      ["Fang", 15.981, -26.11, 2.9, B], ["Alniyat", 16.353, -25.59, 2.9, B], ["Paikauhale", 16.598, -28.22, 2.8, B],
      ["Larawag", 16.836, -34.29, 2.3, O], ["Xamidimura", 16.864, -38.05, 3.0, B], ["Zeta Sco", 16.910, -42.36, 3.6, O],
      ["Eta Sco", 17.203, -43.24, 3.3, W], ["Sargas", 17.622, -43.00, 1.9, Y], ["Iota Sco", 17.793, -40.13, 3.0, Y],
      ["Girtab", 17.708, -39.03, 2.4, B], ["Shaula", 17.560, -37.10, 1.6, B]],
    lines: [[2, 1], [1, 3], [1, 4], [4, 0], [0, 5], [5, 6], [6, 7], [7, 8], [8, 9], [9, 10], [10, 11], [11, 12], [12, 13]] },
  { name: "Leo", stars: [["Regulus", 10.139, 11.97, 1.4, B], ["Al Jabhah", 10.122, 16.76, 3.5, W], ["Algieba", 10.333, 19.84, 2.0, O],
      ["Adhafera", 10.278, 23.42, 3.4, W], ["Rasalas", 9.879, 26.01, 3.9, O], ["Ras Elased", 9.764, 23.77, 3.0, Y],
      ["Zosma", 11.235, 20.52, 2.6, W], ["Chertan", 11.237, 15.43, 3.3, W], ["Denebola", 11.818, 14.57, 2.1, W]],
    lines: [[0, 1], [1, 2], [2, 3], [3, 4], [4, 5], [2, 6], [6, 8], [8, 7], [7, 0], [6, 7]] },
  { name: "Crux", stars: [["Acrux", 12.443, -63.10, 0.8, B], ["Mimosa", 12.795, -59.69, 1.3, B], ["Gacrux", 12.519, -57.11, 1.6, R],
      ["Imai", 12.252, -58.75, 2.8, B]],
    lines: [[0, 2], [1, 3]] },
  { name: "Pegasus & Andromeda", stars: [["Markab", 23.079, 15.21, 2.5, W], ["Scheat", 23.063, 28.08, 2.4, R], ["Algenib", 0.220, 15.18, 2.8, B],
      ["Alpheratz", 0.140, 29.09, 2.1, B], ["Delta And", 0.656, 30.86, 3.3, O], ["Mirach", 1.162, 35.62, 2.1, R], ["Almach", 2.065, 42.33, 2.1, O]],
    lines: [[0, 1], [1, 3], [3, 2], [2, 0], [3, 4], [4, 5], [5, 6]] },
];

// RA/Dec -> a point on the sky sphere (y = celestial north). East is to the left when you look out at it.
export function skyPoint(raHours, decDeg, radius = 100) {
  const ra = (raHours / 24) * Math.PI * 2, dec = (decDeg * Math.PI) / 180;
  return [radius * Math.cos(dec) * Math.cos(ra), radius * Math.sin(dec), -radius * Math.cos(dec) * Math.sin(ra)];
}

// Brighter star, bigger point: magnitude -1.5 -> ~3.4, magnitude 5 -> ~0.6.
export function starSize(mag) {
  return Math.max(0.5, Math.min(3.4, 2.2 * Math.pow(0.78, mag - 0.5) ));
}

// The whole sky for a seed: the named constellations, a faint background starfield (more faint stars than
// bright ones, like the real sky), and a handful of distant galaxies. Performance mode keeps every
// constellation and drops two thirds of the faint field.
export function skyLayout(seed = 7, perf = false) {
  const r = rng(seed);
  const stars = [], lines = [];
  CONSTELLATIONS.forEach((c, ci) => {
    const base = stars.length;
    c.stars.forEach(([name, ra, dec, mag, color]) =>
      stars.push({ p: skyPoint(ra, dec, 100), size: starSize(mag), color, name, con: ci, mag }));
    c.lines.forEach(([a, b]) => lines.push([base + a, base + b]));
  });
  const field = [];
  const n = perf ? 700 : 2100;
  for (let i = 0; i < n; i++) {
    const u = r() * 2 - 1, th = r() * Math.PI * 2, s = Math.sqrt(1 - u * u);
    const mag = 3.5 + 3.2 * Math.pow(r(), 0.45);                    // mostly faint
    const tint = r();
    const color = tint < 0.18 ? B : tint < 0.72 ? W : tint < 0.92 ? Y : O;
    field.push({ p: [104 * s * Math.cos(th), 104 * u, 104 * s * Math.sin(th)], size: starSize(mag) * 0.8, color, mag });
  }
  const galaxies = [];
  const kinds = ["spiral", "spiral", "spiral", "edge", "elliptical", "spiral"];
  const opening = [[2.2, 34], [8.6, -12]];                         // RA hours / Dec: beside Taurus and below Gemini
  for (let i = 0; i < (perf ? 4 : 6); i++) {
    const [ra, dec] = i < opening.length ? opening[i] : [r() * 24, -25 + r() * 65];
    galaxies.push({ p: skyPoint(ra, dec, 120), kind: kinds[i], size: 14 + r() * 12,
                    tilt: r() * Math.PI, spin: (r() < 0.5 ? -1 : 1) * (0.006 + r() * 0.01), seed: Math.floor(r() * 1e9),
                    hue: r() });
  }
  return { stars, lines, field, galaxies };
}

// ---------------- the orb's displacement envelope ----------------
// How much is going on: small base + slow breath + voice + bass, clamped. At rest it barely ripples.
export function displacementScale(p, t, level) {
  const breath = Math.sin(t * 0.7) * 0.5 + 0.5;
  const v = p.base + breath * 0.04 * (p.amp > 0.1 ? 1 : 0.2) + level.voice * p.amp * 0.55 + level.bass * p.amp * 0.35;
  return Math.max(-0.45, Math.min(0.45, v));
}
