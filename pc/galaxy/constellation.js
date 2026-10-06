// The helper constellation (2026-10-03, Trillion "Cosmic Interface" Tiers 4-6): Jenna's real helpers orbit her orb.
// Generated avatars (no art needed), labels that follow each helper and fade as it passes behind the orb, a slow
// breathing glow, and real reactions: dispatch() fires a beam out and back with a flare and a sonar ring; working
// helpers (from her live job list) pulse. Plugs into the galaxy's orb layer (galaxy.orbLayer / galaxy.onFrame).
import * as THREE from "/galaxy/three.module.min.js";

const PALETTE = ["#29B885", "#38BDF8", "#A78BFA", "#E88FB3", "#5EEAD4", "#818CF8", "#F0ABFC", "#34D399", "#60A5FA"];
const EASE = (a, b, k, dt) => a + (b - a) * (1 - Math.pow(1 - k, dt * 60));   // the galaxy's frame-rate-independent ease
const hash01 = (s) => { let h = 0x811c9dc5; for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 0x01000193); } return (h >>> 0) / 4294967296; };

let glowTex = null;
function glow() {
  if (glowTex) return glowTex;
  const c = document.createElement("canvas"); c.width = c.height = 128;
  const g = c.getContext("2d"), r = g.createRadialGradient(64, 64, 0, 64, 64, 64);
  r.addColorStop(0, "rgba(255,255,255,1)"); r.addColorStop(0.3, "rgba(255,255,255,.4)"); r.addColorStop(1, "rgba(255,255,255,0)");
  g.fillStyle = r; g.fillRect(0, 0, 128, 128);
  glowTex = new THREE.CanvasTexture(c); glowTex.colorSpace = THREE.SRGBColorSpace; return glowTex;
}

// avatar: a soft halo, a disc fading from a dark core to the accent, a thin rim, the initial in the middle
function avatarTexture(name, color) {
  const c = document.createElement("canvas"); c.width = c.height = 128;
  const g = c.getContext("2d");
  const halo = g.createRadialGradient(64, 64, 30, 64, 64, 64); halo.addColorStop(0, color + "88"); halo.addColorStop(1, color + "00");
  g.fillStyle = halo; g.fillRect(0, 0, 128, 128);
  const disc = g.createRadialGradient(64, 64, 4, 64, 64, 40); disc.addColorStop(0, "#0b1018"); disc.addColorStop(1, color);
  g.beginPath(); g.arc(64, 64, 40, 0, Math.PI * 2); g.fillStyle = disc; g.fill();
  g.lineWidth = 2; g.strokeStyle = "rgba(255,255,255,.75)"; g.stroke();
  g.fillStyle = "#ffffff"; g.font = "600 34px system-ui, sans-serif"; g.textAlign = "center"; g.textBaseline = "middle";
  g.fillText((name.trim()[0] || "?").toUpperCase(), 64, 66);
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; return t;
}

export function createConstellation(galaxy, agents = []) {
  const { scene, camera, container } = galaxy.orbLayer();
  const root = new THREE.Group(); scene.add(root);
  const layer = document.createElement("div"); layer.className = "constellation";
  layer.style.cssText = "position:absolute;inset:0;pointer-events:none;overflow:hidden;";
  container.appendChild(layer);
  const items = new Map(), effects = [];
  const v = new THREE.Vector3();

  function add(a, i = items.size) {
    if (items.has(a.id)) return items.get(a.id);
    const color = a.color || PALETTE[i % PALETTE.length];
    const g = new THREE.Group();
    const halo = new THREE.Sprite(new THREE.SpriteMaterial({ map: glow(), color, transparent: true, opacity: 0.5,
      blending: THREE.AdditiveBlending, depthWrite: false }));
    halo.scale.setScalar(0.62);
    const face = new THREE.Sprite(new THREE.SpriteMaterial({ map: avatarTexture(a.name, color), transparent: true, depthWrite: false }));
    face.scale.setScalar(0.3);
    g.add(halo, face); root.add(g);
    const label = document.createElement("div");
    label.style.cssText = "position:absolute;left:0;top:0;transform:translate(-50%,0);text-align:center;white-space:nowrap;" +
      "font:12px/1.25 system-ui,sans-serif;color:#e8edf5;text-shadow:0 0 6px #000;opacity:0;transition:opacity .2s;pointer-events:auto;";
    const nm = document.createElement("b"); nm.textContent = a.name;
    const sp = document.createElement("div"); sp.textContent = a.specialty || ""; sp.style.cssText = "font-size:10.5px;opacity:.7;max-width:180px;overflow:hidden;text-overflow:ellipsis;";
    label.append(nm, sp); label.title = a.specialty || ""; layer.appendChild(label);
    const h = hash01(a.id);
    const it = { a, color, g, halo, face, label, placed: false,
      // an ellipse sized to the visible area each frame (sx, sy = share of it), turned in the screen plane by `roll`,
      // with only a little depth so a helper never swings up to the camera
      // One shared orbit, evenly spaced, all turning together like a carousel (2026-10-05). Each helper used to
      // have its own ellipse, speed and direction, so they crossed and piled up on top of each other and some ran
      // off the screen edge. Now they keep their spacing and stay inside the view.
      orbit: { sx: 0.82, sy: 0.7, speed: 0.045, phase: 0, roll: -0.18, depth: 0.25 + 0.15 * h },
      flare: 0, working: false, workGlow: 0, breathe: h * 6.28 };
    items.set(a.id, it);
    return it;
  }
  agents.forEach((a, i) => add(a, i));

  // a thick glowing beam: a bright core and a wide faint sheath, both thin cylinders stretched between two points
  function beam(color) {
    const mk = (r, o) => new THREE.Mesh(new THREE.CylinderGeometry(r, r, 1, 8, 1, true), new THREE.MeshBasicMaterial({
      color, transparent: true, opacity: o, blending: THREE.AdditiveBlending, depthWrite: false }));
    const b = new THREE.Group(); b.add(mk(0.012, 0.9), mk(0.04, 0.22)); root.add(b); return b;
  }
  function placeBeam(b, from, to, frac) {
    const end = from.clone().lerp(to, frac), d = end.clone().sub(from), len = Math.max(d.length(), 1e-4);
    b.position.copy(from).addScaledVector(d, 0.5);
    b.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), d.normalize()); b.scale.set(1, len, 1);
  }
  function ping(at, color, size = 0.5, dur = 1.2) {   // an expanding, fading ring facing the camera (sonar)
    const m = new THREE.Mesh(new THREE.RingGeometry(0.42, 0.5, 48), new THREE.MeshBasicMaterial({ color, transparent: true,
      opacity: 0.8, side: THREE.DoubleSide, blending: THREE.AdditiveBlending, depthWrite: false }));
    m.position.copy(at); root.add(m);
    effects.push({ kind: "ping", m, t0: performance.now(), dur: dur * 1000, size });
  }

  function dispatch(id) {
    const it = items.get(id) || items.get(String(id).replace(/^agent:/, ""));
    if (!it) return false;   // an unknown helper: no animation (never a beam to nowhere)
    ping(new THREE.Vector3(), it.color, 0.45, 0.9);   // the "sending" beat at the orb
    effects.push({ kind: "beam", it, b: beam(it.color), t0: performance.now(), dur: 2600, pinged: false });
    return true;
  }
  function setWorking(ids) {
    const want = new Set(ids);
    for (const [id, it] of items) it.working = want.has(id);
  }

  const hide = () => layer.style.display = "none", show = () => layer.style.display = "";
  const off = galaxy.onFrame((dt, ctx) => {
    const small = container.clientWidth < 700;   // the constellation hides on phones (no room around the orb)
    root.visible = !small; small ? hide() : show();
    if (small) return;
    const w = container.clientWidth, hgt = container.clientHeight, now = performance.now();
    // the visible half-size at the orb's depth (camera distance changes on tall screens)
    const halfH = Math.tan(THREE.MathUtils.degToRad(camera.fov / 2)) * camera.position.z, halfW = halfH * camera.aspect;
    const light = container.dataset.theme === "light";
    // orb's screen radius, to hide labels directly behind it
    v.set(1.1, 0, 0).project(camera); const orbR = Math.abs(v.x) * w / 2;
    const all = [...items.values()];
    all.forEach((it, k) => { it.orbit.phase = (k / all.length) * Math.PI * 2; });   // even spacing for any count
    for (const it of all) {
      const o = it.orbit, t = ctx.reduced ? o.phase : o.phase + ctx.clock * o.speed;
      // clear of the orb, but never wider than the view minus the avatar itself (a floor of 1.9 put Scout half off
      // the screen in a 900 px window)
      const rx = Math.min(halfW - 0.32, Math.max(1.6, halfW * o.sx));
      const ex = Math.cos(t) * rx, ey = Math.sin(t) * Math.min(halfH * o.sy, halfH - 0.3);
      it.g.position.set(ex * Math.cos(o.roll) - ey * Math.sin(o.roll), ex * Math.sin(o.roll) + ey * Math.cos(o.roll),
                        Math.sin(t + 0.6) * 0.9 * o.depth);   // a gentle tilt: in front for part of the lap
      it.flare = EASE(it.flare, 0, 0.04, dt);
      it.workGlow = EASE(it.workGlow, it.working ? 1 : 0, 0.05, dt);
      const breathe = 0.5 + 0.08 * Math.sin(ctx.clock * 1.1 + it.breathe);
      const pulse = it.workGlow * (0.35 + 0.35 * (0.5 + 0.5 * Math.sin(now / 260)));
      it.halo.material.opacity = Math.min(1, breathe + pulse + it.flare * 0.6);
      it.halo.scale.setScalar(0.62 * (1 + it.flare * 0.8 + it.workGlow * 0.25));
      it.face.scale.setScalar(0.3 * (1 + it.flare * 0.25));
      it.label.style.color = light ? "#1d2633" : "#e8edf5"; it.label.style.textShadow = light ? "0 0 6px #fff" : "0 0 6px #000";
      // label: below the avatar on screen; dim on the far side, hidden right behind the orb, stacked by depth
      v.copy(it.g.position).project(camera);
      const sx = (v.x * 0.5 + 0.5) * w, sy = (-v.y * 0.5 + 0.5) * hgt, far = it.g.position.z < 0;
      const behind = far && Math.hypot(sx - w / 2, sy - hgt / 2) < orbR;
      it.lx = Math.min(Math.max(sx, 90), w - 90);   // keep the name on screen near the edges
      it.ly = sy + 20; it.front = 1 - v.z; it.hidden = behind;
      it.label.style.opacity = behind ? "0" : far ? "0.38" : "0.92";
      it.label.style.zIndex = String(Math.round((1 - v.z) * 1000));
      it.face.material.opacity = behind ? 0.25 : 1;
      it.placed = true;
    }
    // labels never sit on top of each other: front-most first, any later one that would overlap moves just below
    const placed = [];
    for (const it of [...items.values()].filter(x => !x.hidden).sort((a, b) => b.front - a.front)) {
      const half = (it.lw ||= it.label.offsetWidth || 140) / 2, tall = 30;
      let y = it.ly;
      for (let k = 0; k < 6; k++) {
        const hit = placed.find(q => Math.abs(q.x - it.lx) < q.half + half + 6 && Math.abs(q.y - y) < tall);
        if (!hit) break;
        y = hit.y + tall;
      }
      placed.push({ x: it.lx, y, half });
      it.label.style.transform = `translate(${it.lx.toFixed(1)}px, ${y.toFixed(1)}px) translate(-50%, 0)`;
    }
    for (let i = effects.length - 1; i >= 0; i--) {
      const e = effects[i], k = (now - e.t0) / e.dur;
      if (e.kind === "ping") {
        if (k >= 1) { root.remove(e.m); e.m.geometry.dispose(); e.m.material.dispose(); effects.splice(i, 1); continue; }
        e.m.scale.setScalar(e.size * (0.3 + 1.6 * k)); e.m.material.opacity = 0.8 * (1 - k); e.m.lookAt(camera.position);
      } else {
        if (k >= 1) { root.remove(e.b); e.b.traverse((x) => { if (x.geometry) { x.geometry.dispose(); x.material.dispose(); } }); effects.splice(i, 1); continue; }
        const out = k < 0.25 ? k / 0.25 : k < 0.55 ? 1 : 1 - (k - 0.55) / 0.45;   // race out, hold, ease back
        placeBeam(e.b, new THREE.Vector3(), e.it.g.position, Math.max(out, 0.001));
        e.b.children.forEach((c, j) => { c.material.opacity = (j ? 0.22 : 0.9) * Math.min(1, out * 1.5); });
        e.it.flare = Math.max(e.it.flare, Math.sin(Math.PI * Math.min(1, k / 0.8)));
        if (!e.pinged && k > 0.4) { e.pinged = true; ping(e.it.g.position.clone(), e.it.color, 0.32, 1.3); }
      }
    }
  });

  return {
    add: (a) => add(a), dispatch, setWorking, ids: () => [...items.keys()],
    destroy() {
      off(); layer.remove(); scene.remove(root);
      root.traverse((x) => { if (x.geometry) x.geometry.dispose(); if (x.material) { if (x.material.map && x.material.map !== glowTex) x.material.map.dispose(); x.material.dispose(); } });
    },
  };
}
