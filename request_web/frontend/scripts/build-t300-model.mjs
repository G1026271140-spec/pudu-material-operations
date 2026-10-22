// Reference-image reconstruction, not CAD/photogrammetry or a measured assembly.
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import * as THREE from 'three';
import { RoundedBoxGeometry } from 'three/addons/geometries/RoundedBoxGeometry.js';
import { TextGeometry } from 'three/addons/geometries/TextGeometry.js';
import { FontLoader } from 'three/addons/loaders/FontLoader.js';
import { GLTFExporter } from 'three/addons/exporters/GLTFExporter.js';
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js';

const here = path.dirname(fileURLToPath(import.meta.url));
const output = path.resolve(here, '../../../assets/category_models');
const font = new FontLoader().parse(JSON.parse(await fs.readFile(path.join(here, 'helvetiker_regular.typeface.json'), 'utf8')));
const colors = {white:0xd5d3cc, cap:0x777c7d, gray:0x737778, dark:0x363b3e,
  black:0x181c1f, tan:0xb6aa7c, tanDark:0x92845d, orange:0xb9601d,
  blue:0x1556aa, yellow:0xe6c62a, red:0xa52b27, face:0x303436, eye:0xe5e5df};
const geometryByColor = new Map();
let parts = 0;
function piece(geometry, color, xyz, rotation=[0,0,0], scale=[1,1,1]) {
  const mesh = new THREE.Mesh(geometry);
  mesh.position.set(...xyz); mesh.rotation.set(...rotation); mesh.scale.set(...scale); mesh.updateMatrix();
  const transformed = (geometry.index ? geometry.toNonIndexed() : geometry.clone()).applyMatrix4(mesh.matrix);
  transformed.deleteAttribute('uv');
  if (!geometryByColor.has(color)) geometryByColor.set(color, []);
  geometryByColor.get(color).push(transformed); parts++;
}
function box(x,y,z,w,h,d,color='gray',rotation=[0,0,0], bevel=.025) {
  piece(new RoundedBoxGeometry(w,h,d,1,Math.min(bevel,w/5,h/5,d/5)),color,[x,y,z],rotation);
}
function cylinder(x,y,z,r,h,color='gray',rotation=[0,0,0],segments=16) {
  piece(new THREE.CylinderGeometry(r,r,h,segments),color,[x,y,z],rotation);
}
function stud(x,y,z,color='gray',r=.12) { cylinder(x,y,z,r,.075,color); }
function text(value,x,y,z,size,color='eye',rotation=[0,0,0]) {
  const geometry = new TextGeometry(value,{font,size,depth:.009,curveSegments:3});
  geometry.computeBoundingBox(); const b=geometry.boundingBox;
  geometry.translate(-(b.max.x+b.min.x)/2,-(b.max.y+b.min.y)/2,0);
  piece(geometry,color,[x,y,z],rotation);
}
function brick(x,y,z,w,h,d,color,studs=false) {
  box(x,y,z,w-.018,h-.018,d-.018,color);
  if(studs) for(let a=-w/2+.24;a<w/2-.1;a+=.48) for(let b=-d/2+.24;b<d/2-.1;b+=.48) stud(x+a,y+h/2+.035,z+b,color);
}
// Yellow-edged base and separate floor tiles.
box(0,0,0,8.2,.18,8.2,'yellow');
for(let x=0;x<8;x++) for(let z=0;z<8;z++) box(x-3.5,.17,z-3.5,.98,.18,.98,'cap', [0,0,0],.014);
// Real thickness, seams and studs on both warehouse walls, including the back.
for(let layer=0;layer<9;layer++) {
  const y=.5+layer*.48;
  for(let segment=0;segment<4;segment++) {
    brick(segment*2-3,y,-3.88,2,.48,.34,'white');
    brick(-3.88,y,segment*2-3,.34,.48,2,'white');
  }
}
for(let n=0;n<4;n++) { box(n*2-3,4.83,-3.88,1.98,.17,.48,'cap'); box(-3.88,4.83,n*2-3,.48,.17,1.98,'cap'); }
// Left shelf: blue columns, orange decks, stacked individual cartons.
for(const z of [-2.8,1.5]) {
  box(-3.18,2.4,z,.18,4.15,.2,'blue');
  box(-2.37,2.4,z,.18,4.15,.2,'blue');
  for(let k=0;k<5;k++) box(-3.2,.65+k*.75,z+.18,.14,.5,.12,'blue',[.4,0,0]);
}
for(let level=0;level<4;level++) {
  const y=.65+level*1.02;
  box(-2.78,y,-.65,1.1,.15,4.5,'orange');
  for(let n=0;n<3;n++) {
    const z=-2.1+n*1.27, color=(n+level)%3===0?'dark':'tan';
    box(-2.78,y+.43,z,.92,.66,1.09,color);
    box(-2.78,y+.8,z,.97,.1,1.13,color);
  }
}
// Back shelf and parcels.
box(.65,2.7,-3.22,3.5,.15,.86,'orange');
for(const [x,w,h] of [[-.5,.95,.7],[.65,.43,.65],[1.4,.35,.32],[2.1,.7,.88]]) {
  box(x,2.77+h/2,-3.15,w,h,.7,'tan'); box(x,2.8+h,-3.15,w+.035,.08,.74,'tan');
}
// Black vertical rails and hazard notice.
for(const x of [2.67,3.46]) box(x,2.3,-3.56,.27,3.6,.32,'black');
box(3.06,2.65,-3.27,1.28,.9,.2,'cap');
const hazard = new THREE.Shape(); hazard.moveTo(0,.34); hazard.lineTo(-.34,-.27); hazard.lineTo(.34,-.27); hazard.closePath();
piece(new THREE.ShapeGeometry(hazard),'black',[3.06,2.64,-3.153]);
piece(new THREE.ShapeGeometry(hazard),'yellow',[3.06,2.64,-3.145],[0,0,0],[.87,.87,1]);
text('!',3.06,2.65,-3.12,.32,'black');
box(.0,4.12,-3.62,2.0,.75,.15,'white'); text('PUDU',.0,4.12,-3.53,.31,'blue');
// Small wall lamp and directions placard on left side.
box(-3.65,2.38,2.0,.14,.95,1.04,'black');
text('A1',-3.55,2.65,2.0,.18,'yellow',[0,Math.PI/2,0]);
text('RECEIVING',-3.55,2.4,2.0,.075,'eye',[0,Math.PI/2,0]);
text('PICKING',-3.55,2.23,2.0,.075,'eye',[0,Math.PI/2,0]);
box(-3.58,3.05,2.0,.4,.08,.15,'black'); cylinder(-3.36,3.09,2.0,.18,.14,'black');
cylinder(-3.36,2.94,2.0,.31,.07,'dark'); cylinder(-3.36,2.87,2.0,.12,.07,'yellow');
// Gray storage boxes/bins.
for(const [x,z,w,h,d] of [[-3.0,2.5,.65,.7,.7],[2.58,-.55,.95,.65,.92],[2.8,-1.45,.8,.6,.8]]) {
  box(x,.32+h/2,z,w,h,d,'dark'); box(x,.36+h,z,w+.03,.09,d+.03,'dark');
}
// T300 chassis: beveled/octagonal plate, bumpers, wheels and sensor ports.
const robotX=.05, robotZ=.72;
box(robotX,.78,robotZ,3.3,.51,2.65,'dark',[0,0,0],.2);
box(robotX,1.07,robotZ,3.55,.17,2.86,'gray',[0,0,0],.18);
box(robotX,.57,robotZ,2.9,.12,2.3,'black',[0,0,0],.16);
for(const x of [-1.2,1.2]) for(const z of [-.2,1.55]) {
  cylinder(x,.5,z,.27,.22,'black',[0,0,Math.PI/2],20);
  cylinder(x+(x>0?.12:-.12),.5,z,.15,.02,'cap',[0,0,Math.PI/2],20);
}
for(const x of [-1.23,-.62,.62,1.23]) box(x,.78,2.055,.24,.08,.026,'black');
for(const x of [-.45,.45]) { cylinder(x,.76,2.085,.15,.05,'cap',[Math.PI/2,0,0]); cylinder(x,.76,2.12,.1,.03,'black',[Math.PI/2,0,0]); }
for(let x=-1.35;x<1.6;x+=.46) for(let z=-.35;z<1.95;z+=.46) stud(x,1.2,z,'gray');
// Right mast made from separate brick courses, blue hinge wheels and handles.
for(let n=0;n<7;n++) brick(1.18,1.42+n*.43,.35,.56,.43,.63,'gray');
box(1.18,4.65,.35,2.02,1.06,.27,'dark'); box(1.18,4.65,.52,1.85,.9,.07,'face');
for(const x of [.66,1.7]) piece(new THREE.SphereGeometry(1,16,10),'eye',[x,4.7,.57],[0,0,0],[.12,.17,.018]);
const smile=[]; for(let i=0;i<=16;i++) {const a=Math.PI+i*Math.PI/16;smile.push(new THREE.Vector3(1.18+Math.cos(a)*.13,4.62+Math.sin(a)*.14,.584));}
piece(new THREE.TubeGeometry(new THREE.CatmullRomCurve3(smile),16,.014,6,false),'eye',[0,0,0]);
for(const x of [.8,1.56]) { cylinder(x,4.02,.35,.21,.13,'blue',[0,0,Math.PI/2],20); cylinder(x,4.02,.35,.13,.16,'blue',[0,0,Math.PI/2],16); }
cylinder(.7,3.26,.45,.1,.88,'gray',[0,0,Math.PI/2]); cylinder(1.7,3.26,.45,.1,.88,'gray',[0,0,Math.PI/2]);
// Two open stacked crates, including actual gaps for lifting handles.
function crate(cx,cy,cz) {
  const w=1.74,d=1.4,h=.75;
  box(cx,cy+.05,cz,w,.1,d,'tanDark');
  for(const side of [-1,1]) {
    box(cx,cy+.23,cz+side*d/2,w,.34,.11,'tan');
    box(cx,cy+h-.07,cz+side*d/2,w,.14,.11,'tan');
    for(const end of [-1,1]) box(cx+end*.6,cy+.48,cz+side*d/2,.54,.2,.11,'tan');
    box(cx+side*w/2,cy+.4,cz,.11,.7,d,'tan');
  }
  for(const x of [-.72,-.25,.22,.69]) for(const z of [-d/2,d/2]) stud(cx+x,cy+h+.025,cz+z,'tan',.095);
}
crate(-.45,1.22,.83); crate(-.45,1.98,.83);
for(const [x,z,color] of [[-.9,.65,'yellow'],[-.35,.45,'red'],[.12,.5,'blue'],[-.55,1.05,'red'],[.05,1.0,'blue']]) {
  cylinder(x,2.68,z,.15,.28,color);
  piece(new THREE.TorusGeometry(.105,.04,7,16),color,[x,2.83,z],[Math.PI/2,0,0]);
  cylinder(x,2.837,z,.067,.012,'tanDark');
}
// Tilted front display plaque with actual mesh lettering.
// The plaque has a restrained tilt; labels stay readable in the starting view.
box(2.0,.65,3.15,2.15,.98,.11,'dark',[-.65,0,0]);
text('PUDU T300',2.0,.82,3.13,.23,'eye',[-.65,0,0]);
text('Warehouse Logistics',2.0,.60,3.30,.115,'eye',[-.65,0,0]);
for(const x of [1.02,2.98]) cylinder(x,.75,3.49,.035,.025,'yellow',[Math.PI/2,0,0]);
// Collapse hundreds of parts into one draw call per material for mobile use.
const scene = new THREE.Scene(); scene.name='PUDU_T300_Building_Blocks_Reference_Reconstruction';
let triangles=0;
for(const [color,geometries] of geometryByColor) {
  const geometry = mergeGeometries(geometries);
  const material = new THREE.MeshStandardMaterial({color:colors[color],roughness:.66,metalness:.03});
  const mesh = new THREE.Mesh(geometry,material); mesh.name=`Blocks_${color}`;
  mesh.castShadow=true; mesh.receiveShadow=true; scene.add(mesh);
  triangles+=geometry.attributes.position.count/3;
}
scene.userData={referenceReconstruction:true,measuredDimensions:false,nominalScaleOnly:true,
  note:'Reconstructed from four user-supplied reference renders. Hidden details are inferred; not original CAD or a verified build guide.',
  sourceImages:['f639618cf8bef11dfcd97b72f1ff0093.png','b4c5e33ce799ab544428bfd36b4772f8.png','375f3d7da8c4cd2ff9ffa6896556dfc3.png','99b637cf315466bd739ea57dd340a38e.png']};
globalThis.FileReader = class {
  readAsArrayBuffer(blob) { blob.arrayBuffer().then(result=>{this.result=result;this.onloadend?.();}); }
  readAsDataURL(blob) { blob.arrayBuffer().then(result=>{this.result=`data:${blob.type};base64,${Buffer.from(result).toString('base64')}`;this.onloadend?.();}); }
};
await fs.mkdir(output,{recursive:true});
const glb = await new GLTFExporter().parseAsync(scene,{binary:true});
const target=path.join(output,'t300-building-blocks.glb'); await fs.writeFile(target,Buffer.from(glb));
console.log(JSON.stringify({target,parts,meshes:scene.children.length,triangles,bytes:glb.byteLength}));
