/** Genuine 3D geometry, projected with a perspective camera. */
export type Vec3 = { x: number; y: number; z: number };
export type Camera = { yaw: number; pitch: number; zoom: number; panX: number; panY: number };
export const INITIAL_CAMERA: Camera = { yaw: -1.03, pitch: .19, zoom: 1, panX: 0, panY: 0 };
export const clamp = (v: number, min: number, max: number) => Math.max(min, Math.min(max, v));
export function project(p: Vec3, c: Camera, width: number, height: number) {
  const x=p.x*Math.cos(c.yaw)+p.z*Math.sin(c.yaw), z=-p.x*Math.sin(c.yaw)+p.z*Math.cos(c.yaw);
  const y=p.y*Math.cos(c.pitch)-z*Math.sin(c.pitch), depth=p.y*Math.sin(c.pitch)+z*Math.cos(c.pitch);
  const scale=Math.min(width/3.9,height/3.1)*c.zoom*5.8/(5.8-depth);
  return { x:width/2+c.panX+x*scale, y:height*.48+c.panY-y*scale, depth };
}
export function hemisphere(side:number,lat:number,lon:number,lift=0):Vec3 {
  const s=Math.sin(lat), cy=Math.cos(lat), xx=s*Math.cos(lon), zz=s*Math.sin(lon);
  const r=1+.022*Math.sin(24*lat+2.5*Math.sin(lon*3))+.018*Math.sin(lon*19+Math.sin(lat*9)*1.7)+lift;
  return {x:side*(.56+.52*xx*r),y:.13+.95*cy*r-.08*zz,z:1.42*zz*r*(1+.07*cy)};
}
export const brainFaces:{vertices:Vec3[];tone:number}[]=[];
export const folds:Vec3[][]=[];
for(const side of [-1,1]) {
  for(let i=0;i<28;i++)for(let j=0;j<56;j++){
    const p=(a:number,b:number)=>hemisphere(side,a/28*Math.PI,b/56*Math.PI*2);
    brainFaces.push({vertices:[p(i,j),p(i+1,j),p(i+1,j+1),p(i,j+1)],tone:.5+.3*Math.sin(i*.67+j*.55)});
  }
  for(let line=0;line<30;line++)folds.push(Array.from({length:71},(_,t)=>{
    const u=t/70;return hemisphere(side,.15+u*(Math.PI-.3),line/30*Math.PI*2+.12*Math.sin(u*15+line*.8)+.045*Math.sin(u*38+line),.009);
  }));
  for(let crease=0;crease<42;crease++)folds.push(Array.from({length:45},(_,t)=>{
    const u=t/44,lat=.28+(crease%7)/7*2.5+.075*Math.sin(u*13+crease);
    const lon=Math.floor(crease/7)/6*Math.PI*2+u*.85+.08*Math.sin(u*7+crease);
    return hemisphere(side,lat,lon,.012);
  }));
}
// Cerebellum and brainstem form the lower posterior silhouette.
for(let ring=0;ring<18;ring++){
  const lat=(ring+.5)/18*Math.PI;
  folds.push(Array.from({length:71},(_,j)=>{const a=j/70*Math.PI*2;return{x:.73*Math.sin(lat)*Math.cos(a),y:-.7+.47*Math.cos(lat),z:-.89+.52*Math.sin(lat)*Math.sin(a)};}));
}
for(let i=0;i<10;i++){const a=i/10*Math.PI*2;folds.push(Array.from({length:18},(_,j)=>({x:.13*Math.cos(a)*(1-j/30),y:-.68-j*.039,z:-.55+j*.023+.13*Math.sin(a)})));}
function hash(id:string){let v=2166136261;for(const c of id)v=Math.imul(v^c.charCodeAt(0),16777619);return v>>>0;}
export function topicPosition(n:{id:string;x:number;y:number}):Vec3 {
  const seed=hash(n.id),side=seed%2?1:-1;
  return hemisphere(side,.65+(1-n.y)*3.7+((seed>>>4)%100)/1000,Math.asin(clamp((n.x-.5)*2,-.95,.95)),.08);
}
export function fiber(a:Vec3,b:Vec3,offset=0):Vec3[]{return Array.from({length:45},(_,i)=>{const t=i/44,s=Math.sin(t*Math.PI);return{x:a.x*(1-t)+b.x*t+s*offset,y:a.y*(1-t)+b.y*t+s*(.34+offset),z:a.z*(1-t)+b.z*t-s*(.25+offset*.5)};});}
export function zoomCamera(c:Camera,factor:number):Camera{return{...c,zoom:clamp(c.zoom*factor,.55,3.5)};}
