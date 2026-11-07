// viewer.js
// An interactive 3D viewer pop-up for the Community page.
//
// Beginner notes:
//   - OrbitControls lets the visitor drag to rotate, scroll to zoom and
//     right-drag to move the model.
//   - Everything is created when the pop-up opens and thrown away when it
//     closes, so no memory (or WebGL canvas) is left behind.
//
// Needs the import map for "three" that community.html already has, and
// thumbnail.js, which knows how to load OBJ, GLB, STL and PLY files.

import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";
import { loadModel, supports } from "./thumbnail.js";

const el = {
  modal: document.getElementById("viewerModal"),
  stage: document.getElementById("viewerStage"),
  status: document.getElementById("viewerStatus"),
  title: document.getElementById("viewerTitle"),
  meta: document.getElementById("viewerMeta"),
  close: document.getElementById("viewerClose"),
  rotate: document.getElementById("viewerRotate"),
  wire: document.getElementById("viewerWire"),
  reset: document.getElementById("viewerReset"),
};

let scene3d = null; // everything that must be cleaned up on close
let openToken = 0; // lets us ignore a slow load after the pop-up was closed
let wireframe = false;

function formatSize(bytes) {
  if (!bytes) return "";
  const units = ["B", "KB", "MB", "GB"];
  let n = bytes;
  let i = 0;
  while (n >= 1024 && i < units.length - 1) {
    n /= 1024;
    i += 1;
  }
  return `${n.toFixed(i ? 1 : 0)} ${units[i]}`;
}

function setStatus(text) {
  el.status.textContent = text;
}

function syncButtons() {
  const rotating = scene3d ? scene3d.controls.autoRotate : true;
  el.rotate.textContent = `Auto-rotate: ${rotating ? "on" : "off"}`;
  el.wire.textContent = `Wireframe: ${wireframe ? "on" : "off"}`;
}

// ---------- Download with a progress number ----------

async function fetchWithProgress(url, onProgress) {
  const response = await fetch(url);
  if (!response.ok) throw new Error("The model file could not be downloaded.");

  const total = Number(response.headers.get("content-length")) || 0;
  if (!response.body || !total) return await response.blob();

  const reader = response.body.getReader();
  const chunks = [];
  let received = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    chunks.push(value);
    received += value.length;
    onProgress(Math.min(100, Math.round((received / total) * 100)));
  }
  return new Blob(chunks);
}

// ---------- Clean-up ----------

function disposeObject(object) {
  const materials = new Set();
  object.traverse((child) => {
    if (child.geometry) child.geometry.dispose();
    if (child.material) {
      (Array.isArray(child.material) ? child.material : [child.material]).forEach(
        (m) => materials.add(m),
      );
    }
  });
  materials.forEach((m) => {
    Object.values(m).forEach((value) => {
      if (value && value.isTexture) value.dispose();
    });
    m.dispose();
  });
}

function destroyScene() {
  if (!scene3d) return;
  const s = scene3d;
  scene3d = null;

  s.renderer.setAnimationLoop(null);
  s.observer.disconnect();
  s.controls.dispose();
  disposeObject(s.holder);
  s.envTexture.dispose();
  s.pmrem.dispose();
  s.renderer.dispose();
  s.renderer.forceContextLoss();
  s.renderer.domElement.remove();
}

export function close() {
  openToken += 1; // cancels any load that is still running
  destroyScene();
  el.modal.classList.remove("show");
  el.modal.setAttribute("aria-hidden", "true");
  document.body.style.overflow = "";
  wireframe = false;
}

// ---------- Building the 3D view ----------

function countTriangles(object) {
  let triangles = 0;
  object.traverse((child) => {
    if (!child.isMesh) return;
    const g = child.geometry;
    const count = g.index ? g.index.count : g.getAttribute("position").count;
    triangles += Math.floor(count / 3);
  });
  return triangles;
}

function applyWireframe() {
  if (!scene3d) return;
  scene3d.holder.traverse((child) => {
    if (!child.isMesh) return;
    (Array.isArray(child.material) ? child.material : [child.material]).forEach(
      (m) => {
        m.wireframe = wireframe;
      },
    );
  });
}

function startScene(model, baseMeta) {
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  el.stage.appendChild(renderer.domElement);

  const scene = new THREE.Scene();
  const pmrem = new THREE.PMREMGenerator(renderer);
  const envTexture = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
  scene.environment = envTexture;

  const holder = new THREE.Group();
  holder.add(model);
  scene.add(holder);

  const box = new THREE.Box3().setFromObject(holder);
  if (box.isEmpty()) {
    renderer.dispose();
    renderer.domElement.remove();
    throw new Error("The model has no geometry.");
  }
  const center = box.getCenter(new THREE.Vector3());
  const size = box.getSize(new THREE.Vector3());
  const radius = size.length() / 2 || 1;
  holder.position.sub(center); // put the model in the middle

  const camera = new THREE.PerspectiveCamera(40, 1, radius / 100, radius * 100);
  const distance = (radius / Math.sin(THREE.MathUtils.degToRad(20))) * 1.1;
  const home = new THREE.Vector3(1, 0.7, 1).normalize().multiplyScalar(distance);
  camera.position.copy(home);

  scene.add(new THREE.HemisphereLight(0xffffff, 0x8888aa, 0.5));
  const key = new THREE.DirectionalLight(0xffffff, 1.5);
  key.position.set(radius, radius * 1.5, radius);
  scene.add(key);

  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.autoRotate = true;
  controls.autoRotateSpeed = 1.2;
  controls.minDistance = radius * 0.3;
  controls.maxDistance = radius * 8;
  // Stop spinning as soon as the visitor grabs the model
  controls.addEventListener("start", () => {
    controls.autoRotate = false;
    syncButtons();
  });

  function resize() {
    const w = el.stage.clientWidth || 1;
    const h = el.stage.clientHeight || 1;
    renderer.setSize(w, h);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  }
  const observer = new ResizeObserver(resize);
  observer.observe(el.stage);
  resize();

  renderer.setAnimationLoop(() => {
    controls.update();
    renderer.render(scene, camera);
  });

  scene3d = { renderer, controls, camera, home, holder, envTexture, pmrem, observer };

  const dims = [size.x, size.y, size.z].map((n) => +n.toPrecision(3)).join(" × ");
  el.meta.textContent = `${baseMeta} · ${countTriangles(holder).toLocaleString()} triangles · ${dims}`;

  applyWireframe();
  syncButtons();
}

// ---------- Opening the pop-up ----------

export async function open({ url, format, title, size }) {
  close();
  const token = ++openToken;
  const fmt = String(format || "").toLowerCase();
  const baseMeta = [`.${fmt}`, formatSize(size)].filter(Boolean).join(" · ");

  el.title.textContent = title || "3D model";
  el.meta.textContent = baseMeta;
  el.modal.classList.add("show");
  el.modal.setAttribute("aria-hidden", "false");
  document.body.style.overflow = "hidden";
  el.close.focus();
  syncButtons();

  if (!supports(fmt, size)) {
    setStatus(
      "A live 3D view is not available for this file. Download it to open it in your own software.",
    );
    return;
  }

  setStatus("Loading model…");
  try {
    const blob = await fetchWithProgress(url, (percent) => {
      if (token === openToken) setStatus(`Loading model… ${percent}%`);
    });
    if (token !== openToken) return;

    setStatus("Preparing the 3D view…");
    const model = await loadModel(blob, fmt);
    if (token !== openToken) {
      if (model) disposeObject(model);
      return;
    }
    if (!model) throw new Error("Unsupported file.");

    startScene(model, baseMeta);
    setStatus("");
  } catch (error) {
    console.warn("3D viewer could not show the model:", error);
    if (token === openToken) {
      setStatus(
        "This model could not be displayed. It may use features the preview does not support. You can still download it.",
      );
    }
  }
}

// ---------- Buttons and keyboard ----------

el.close.addEventListener("click", close);
el.modal.addEventListener("click", (event) => {
  if (event.target === el.modal) close(); // click on the dark background
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && el.modal.classList.contains("show")) close();
});

el.rotate.addEventListener("click", () => {
  if (!scene3d) return;
  scene3d.controls.autoRotate = !scene3d.controls.autoRotate;
  syncButtons();
});

el.wire.addEventListener("click", () => {
  wireframe = !wireframe;
  applyWireframe();
  syncButtons();
});

el.reset.addEventListener("click", () => {
  if (!scene3d) return;
  scene3d.camera.position.copy(scene3d.home);
  scene3d.controls.target.set(0, 0, 0);
  scene3d.controls.update();
});

// The Community page uses plain scripts, so share the viewer through window
window.AFViewer = { open, close };
window.dispatchEvent(new Event("af-viewer-ready"));
