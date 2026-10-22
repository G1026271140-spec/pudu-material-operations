import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";

export function mountModelScene(host: HTMLElement, url: string, ready: () => void, failed: () => void) {
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.15;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  const canvas = renderer.domElement;
  canvas.tabIndex = 0;
  canvas.setAttribute("aria-label", "3D model. Drag to rotate; pinch or wheel to zoom. Arrow keys rotate; Home resets.");
  canvas.style.touchAction = "none";
  host.appendChild(canvas);
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0xeaf0f3);
  scene.add(new THREE.HemisphereLight(0xffffff, 0x7a8793, 2.5));
  const sun = new THREE.DirectionalLight(0xffffff, 3.2);
  sun.position.set(7, 13, 9); sun.castShadow = true;
  sun.shadow.mapSize.set(1024, 1024);
  Object.assign(sun.shadow.camera, {left:-9,right:9,top:9,bottom:-9,near:.1,far:50});
  sun.shadow.normalBias=.03; scene.add(sun);
  const fill = new THREE.DirectionalLight(0xdce8ff, 1.8); fill.position.set(-7, 8, -5); scene.add(fill);
  const camera = new THREE.PerspectiveCamera(35, 1, .1, 120);
  const controls = new OrbitControls(camera, canvas);
  controls.enablePan = false; controls.enableDamping = false;
  controls.minDistance = 6; controls.maxDistance = 35;
  controls.minPolarAngle = .01; controls.maxPolarAngle = Math.PI-.01;
  controls.target.set(0,2,0);
  const start = new THREE.Vector3(10,8.5,12);
  let stopped=false, frame=0;
  const abort = new AbortController();
  function render() { if(!stopped) renderer.render(scene,camera); }
  function requestRender() { if(!frame && !stopped) frame=requestAnimationFrame(()=>{frame=0;render();}); }
  function reset() { camera.position.copy(start); controls.target.set(0,2,0); controls.update(); requestRender(); }
  function rotate(horizontal: number, vertical=0) {
    const spherical = new THREE.Spherical().setFromVector3(camera.position.clone().sub(controls.target));
    spherical.theta+=horizontal; spherical.phi=THREE.MathUtils.clamp(spherical.phi+vertical,.01,Math.PI-.01);
    camera.position.copy(controls.target).add(new THREE.Vector3().setFromSpherical(spherical)); controls.update(); requestRender();
  }
  function zoom(factor: number) {
    const delta=camera.position.clone().sub(controls.target);
    delta.setLength(THREE.MathUtils.clamp(delta.length()*factor,controls.minDistance,controls.maxDistance));
    camera.position.copy(controls.target).add(delta); controls.update();requestRender();
  }
  const onKey = (event: KeyboardEvent) => {
    const keys:Record<string,()=>void> = {ArrowLeft:()=>rotate(-.16),ArrowRight:()=>rotate(.16),ArrowUp:()=>rotate(0,-.16),ArrowDown:()=>rotate(0,.16),Home:reset,"+":()=>zoom(.85),"-":()=>zoom(1.15)};
    if(keys[event.key]) {event.preventDefault();event.stopPropagation();keys[event.key]();}
  };
  const onLost = (event: Event) => {event.preventDefault();failed();};
  canvas.addEventListener("keydown",onKey);canvas.addEventListener("webglcontextlost",onLost);
  controls.addEventListener("change",requestRender);
  const resize = new ResizeObserver(() => {
    const {width,height}=host.getBoundingClientRect(); if(!width || !height) return;
    camera.aspect=width/height;camera.updateProjectionMatrix();renderer.setSize(width,height,false);requestRender();
  });
  resize.observe(host);reset();
  function disposeObject(object: THREE.Object3D) {
    object.traverse(item => { if(item instanceof THREE.Mesh) {
      item.geometry.dispose();
      for(const material of Array.isArray(item.material)?item.material:[item.material]) material.dispose();
    }});
  }
  void fetch(url,{signal:abort.signal,credentials:"same-origin"}).then(response=>{
    if(!response.ok) throw Error("Model download failed"); return response.arrayBuffer();
  }).then(bytes=>new GLTFLoader().parseAsync(bytes,""))
    .then(gltf=>{
      if(stopped) {disposeObject(gltf.scene);return;}
      gltf.scene.traverse(object=>{if(object instanceof THREE.Mesh) {object.castShadow=true;object.receiveShadow=true;}});
      scene.add(gltf.scene);ready();requestRender();
    }).catch(error=>{if(!stopped && error.name!=="AbortError") failed();});
  return {reset,rotate,zoom,dispose:()=>{
    stopped=true;abort.abort();cancelAnimationFrame(frame);resize.disconnect();
    controls.removeEventListener("change",requestRender);controls.dispose();
    canvas.removeEventListener("keydown",onKey);canvas.removeEventListener("webglcontextlost",onLost);
    disposeObject(scene);renderer.dispose();canvas.remove();
  }};
}
