// thumbnail.js
// Draws a small PNG preview of a 3D model inside the visitor's browser.
//
// How it works (beginner version):
//   1. A "loader" turns the model file into Three.js objects.
//   2. We put the object in a scene with lights and point a camera at it.
//   3. A renderer draws the scene onto a hidden canvas.
//   4. We save that canvas as a PNG image.
//
// The page that loads this file must define an import map for "three"
// (see community.html). Formats supported: OBJ, GLB, STL, PLY.

import * as THREE from "three";
import { OBJLoader } from "three/addons/loaders/OBJLoader.js";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { STLLoader } from "three/addons/loaders/STLLoader.js";
import { PLYLoader } from "three/addons/loaders/PLYLoader.js";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";

const SUPPORTED = ["obj", "glb", "stl", "ply"];
const MAX_BYTES = 30 * 1024 * 1024; // bigger files are skipped (too slow)
const WIDTH = 600;
const HEIGHT = 300; // same 2:1 shape as the card preview area
const TIMEOUT_MS = 25000;

let renderer = null;
let environment = null;

function getRenderer() {
  if (renderer) return renderer;

  renderer = new THREE.WebGLRenderer({
    antialias: true,
    alpha: true, // transparent background, so it fits dark and light themes
    preserveDrawingBuffer: true,
  });
  renderer.setPixelRatio(1);
  renderer.setSize(WIDTH, HEIGHT, false);
  renderer.setClearColor(0x000000, 0);
  renderer.toneMapping = THREE.ACESFilmicToneMapping;

  // Soft studio lighting so shiny (PBR) materials do not look black
  const pmrem = new THREE.PMREMGenerator(renderer);
  environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;

  return renderer;
}

export function supports(format, size) {
  const fmt = String(format || "").toLowerCase();
  if (!SUPPORTED.includes(fmt)) return false;
  return !size || size <= MAX_BYTES;
}

// ---------- Loading ----------

function neutralMaterial(geometry) {
  const hasColors = geometry && geometry.hasAttribute("color");
  return new THREE.MeshStandardMaterial({
    color: hasColors ? 0xffffff : 0xb9b3f0,
    vertexColors: !!hasColors,
    roughness: 0.55,
    metalness: 0.15,
    side: THREE.DoubleSide,
  });
}

function geometryToMesh(geometry) {
  if (!geometry.hasAttribute("normal")) geometry.computeVertexNormals();
  return new THREE.Mesh(geometry, neutralMaterial(geometry));
}

export async function loadModel(blob, format) {
  if (format === "obj") {
    const text = await blob.text();
    const group = new OBJLoader().parse(text);
    const material = neutralMaterial(null);
    group.traverse((child) => {
      if (child.isMesh) {
        if (!child.geometry.hasAttribute("normal")) {
          child.geometry.computeVertexNormals();
        }
        child.material = material; // ignore .mtl colours for the preview
      }
    });
    return group;
  }

  const buffer = await blob.arrayBuffer();

  if (format === "glb") {
    return await new Promise((resolve, reject) => {
      new GLTFLoader().parse(buffer, "", (gltf) => resolve(gltf.scene), reject);
    });
  }
  if (format === "stl") return geometryToMesh(new STLLoader().parse(buffer));
  if (format === "ply") return geometryToMesh(new PLYLoader().parse(buffer));

  return null;
}

// ---------- Drawing ----------

function disposeObject(object) {
  const materials = new Set();
  object.traverse((child) => {
    if (child.geometry) child.geometry.dispose();
    if (child.material) {
      (Array.isArray(child.material)
        ? child.material
        : [child.material]
      ).forEach((m) => materials.add(m));
    }
  });
  materials.forEach((m) => {
    Object.values(m).forEach((value) => {
      if (value && value.isTexture) value.dispose();
    });
    m.dispose();
  });
}

async function drawPreview(blob, format) {
  const model = await loadModel(blob, format);
  if (!model) return null;

  const gl = getRenderer();
  const scene = new THREE.Scene();
  scene.environment = environment;

  // The holder lets us move the model to the middle without touching
  // the model's own position.
  const holder = new THREE.Group();
  holder.add(model);
  scene.add(holder);

  const box = new THREE.Box3().setFromObject(holder);
  if (box.isEmpty()) {
    disposeObject(holder);
    return null;
  }
  const center = box.getCenter(new THREE.Vector3());
  const radius = box.getSize(new THREE.Vector3()).length() / 2 || 1;
  holder.position.sub(center);

  const camera = new THREE.PerspectiveCamera(
    35,
    WIDTH / HEIGHT,
    radius / 100,
    radius * 100,
  );
  const distance =
    (radius / Math.sin(THREE.MathUtils.degToRad(camera.fov / 2))) * 1.05;
  camera.position.set(1, 0.7, 1).normalize().multiplyScalar(distance);
  camera.lookAt(0, 0, 0);

  scene.add(new THREE.HemisphereLight(0xffffff, 0x8888aa, 0.5));
  const key = new THREE.DirectionalLight(0xffffff, 1.8);
  key.position.copy(camera.position);
  scene.add(key);

  gl.render(scene, camera);

  const png = await new Promise((resolve) =>
    gl.domElement.toBlob(resolve, "image/png"),
  );

  disposeObject(holder);
  return png;
}

// ---------- Public API ----------
// Previews are drawn one at a time, so several requests never fight over
// the single shared canvas.

let queue = Promise.resolve();

function withTimeout(promise, ms) {
  return Promise.race([
    promise,
    new Promise((_, reject) =>
      setTimeout(() => reject(new Error("Preview timed out")), ms),
    ),
  ]);
}

export function generate(blob, format) {
  const fmt = String(format || "").toLowerCase();
  if (!blob || !supports(fmt, blob.size)) return Promise.resolve(null);

  const job = queue.then(() => withTimeout(drawPreview(blob, fmt), TIMEOUT_MS));
  queue = job.catch(() => {}); // keep the queue alive after a failure
  return job.catch((error) => {
    console.warn("Preview could not be created:", error);
    return null;
  });
}

// The Community page uses plain (non-module) scripts, so share the tools
// through the window object.
window.AFThumbnails = { supports, generate };
window.dispatchEvent(new Event("af-thumbnails-ready"));
