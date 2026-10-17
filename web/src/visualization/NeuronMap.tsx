import { useEffect, useRef, useState, type CSSProperties } from 'react';
import type { Graph, Node, Edge, Entry } from '../state/model';
import { Icon } from '../components/Icon';
import { brainFaces, folds, INITIAL_CAMERA, project, topicPosition, fiber, zoomCamera, clamp, type Camera, type Vec3 } from './brain';

const palette:Record<string,string>={piano:'#c1abff',friends:'#ffb29a',home:'#88d9c8'};
type Props={graph:Graph;onNode:(node:Node)=>void;onEdge:(edge:Edge)=>void;selected?:string;compact?:boolean;entries?:Entry[];onOpenEntry?:(id:string)=>void};
type Overlay={id:string;x:number;y:number;depth:number};

function BrainScene({graph,onNode,onEdge,selected,entries=[],onOpenEntry}:Props){
  const [pinned,setPinned]=useState<string|null>(null);
  const viewport=useRef<HTMLDivElement>(null),canvas=useRef<HTMLCanvasElement>(null);
  const camera=useRef<Camera>({...INITIAL_CAMERA}),paint=useRef<()=>void>(()=>{});
  const [overlays,setOverlays]=useState<Overlay[]>([]),[edges,setEdges]=useState<Overlay[]>([]),[zoom,setZoom]=useState(100);
  const latest=useRef({graph,onNode,onEdge,selected});latest.current={graph,onNode,onEdge,selected};
  const dragged=useRef(false);
  useEffect(()=>{
    const outside=(event:PointerEvent)=>{if(!(event.target as HTMLElement).closest('.brain-topic'))setPinned(null);};
    const escape=(event:KeyboardEvent)=>{if(event.key==='Escape')setPinned(null);};
    document.addEventListener('pointerdown',outside);document.addEventListener('keydown',escape);
    return()=>{document.removeEventListener('pointerdown',outside);document.removeEventListener('keydown',escape);};
  },[]);
  useEffect(()=>{
    const el=viewport.current!,ctx=canvas.current!.getContext('2d');if(!ctx)return;
    let frame=0,width=0,height=0;
    const request=()=>{if(!frame)frame=requestAnimationFrame(draw);};paint.current=request;
    function line(points:Vec3[],stroke:string,lineWidth:number){
      ctx!.beginPath();points.forEach((p,i)=>{const v=project(p,camera.current,width,height);if(i)ctx!.lineTo(v.x,v.y);else ctx!.moveTo(v.x,v.y);});
      ctx!.strokeStyle=stroke;ctx!.lineWidth=lineWidth;ctx!.stroke();
    }
    function draw(){
      frame=0;if(!ctx||!width||!height)return;ctx.clearRect(0,0,width,height);const c=camera.current;
      const faces=brainFaces.map(f=>({...f,points:f.vertices.map(p=>project(p,c,width,height))}));
      faces.sort((a,b)=>a.points.reduce((s,p)=>s+p.depth,0)-b.points.reduce((s,p)=>s+p.depth,0));
      for(const face of faces){
        ctx.beginPath();face.points.forEach((p,i)=>{if(i)ctx.lineTo(p.x,p.y);else ctx.moveTo(p.x,p.y);});ctx.closePath();
        const depth=face.points.reduce((s,p)=>s+p.depth,0)/4;
        ctx.fillStyle=`rgba(87,116,132,${.017+face.tone*.015+(depth+1.5)*.005})`;ctx.fill();
      }
      for(const points of folds){const depth=points.reduce((s,p)=>s+project(p,c,width,height).depth,0)/points.length;line(points,`rgba(154,188,199,${clamp(.17+depth*.055,.07,.29)})`,.72);}
      const current=latest.current.graph,positions=new Map(current.nodes.map(n=>[n.id,topicPosition(n)]));
      const edgeAnchors:Overlay[]=[];
      for(const e of current.edges){
        const a=positions.get(e.source),b=positions.get(e.target);if(!a||!b)continue;
        for(let i=0;i<9;i++){ctx.globalAlpha=i===4?.8:.25;line(fiber(a,b,(i-4)*.025),i%2?palette[e.source]||'#c1abff':palette[e.target]||'#88d9c8',i===4?1+e.shared_entry_count*.35:.6);}ctx.globalAlpha=1;
        edgeAnchors.push({id:e.source+'/'+e.target,...project(fiber(a,b)[22],c,width,height)});
      }
      const nodes=current.nodes.map(n=>({n,p:project(positions.get(n.id)!,c,width,height)})).sort((a,b)=>a.p.depth-b.p.depth);
      for(const{n,p}of nodes){
        const color=palette[n.id]||'#c1abff',radius=(5+Math.sqrt(n.count)*2.6)*clamp(c.zoom,.8,1.6);
        if(n.count){const glow=ctx.createRadialGradient(p.x,p.y,0,p.x,p.y,radius*4.5);glow.addColorStop(0,color+'99');glow.addColorStop(.3,color+'33');glow.addColorStop(1,color+'00');ctx.fillStyle=glow;ctx.globalAlpha=n.brightness;ctx.beginPath();ctx.arc(p.x,p.y,radius*4.5,0,Math.PI*2);ctx.fill();ctx.globalAlpha=1;}
        ctx.beginPath();ctx.arc(p.x,p.y,radius,0,Math.PI*2);ctx.fillStyle=n.count?color:'#121b2a';ctx.strokeStyle=color;ctx.lineWidth=1;ctx.fill();ctx.stroke();
        if(n.count){const light=ctx.createRadialGradient(p.x-radius*.3,p.y-radius*.35,0,p.x,p.y,radius);light.addColorStop(0,'#ffffffda');light.addColorStop(.4,'#ffffff28');light.addColorStop(1,'#00000044');ctx.fillStyle=light;ctx.fill();}
      }
      setOverlays(nodes.map(({n,p})=>({id:n.id,...p})));setEdges(edgeAnchors);setZoom(Math.round(c.zoom*100));
    }
    const resize=()=>{width=el.clientWidth;height=el.clientHeight;const dpr=Math.min(window.devicePixelRatio||1,2);canvas.current!.width=Math.round(width*dpr);canvas.current!.height=Math.round(height*dpr);ctx.setTransform(dpr,0,0,dpr,0,0);request();};
    const observer=new ResizeObserver(resize);observer.observe(el);resize();
    const pointers=new Map<number,{x:number;y:number}>();let pinchDistance=0;
    const down=(e:PointerEvent)=>{if((e.target as HTMLElement).closest('button, .neuron-tooltip')){dragged.current=false;return;}el.focus({preventScroll:true});el.setPointerCapture(e.pointerId);pointers.set(e.pointerId,{x:e.clientX,y:e.clientY});dragged.current=false;if(pointers.size===2){const[a,b]=[...pointers.values()];pinchDistance=Math.hypot(a.x-b.x,a.y-b.y);}el.classList.add('is-dragging');};
    const move=(e:PointerEvent)=>{
      const old=pointers.get(e.pointerId);if(!old)return;const dx=e.clientX-old.x,dy=e.clientY-old.y;if(Math.abs(dx)+Math.abs(dy)>2)dragged.current=true;pointers.set(e.pointerId,{x:e.clientX,y:e.clientY});
      if(pointers.size===2){const[a,b]=[...pointers.values()],distance=Math.hypot(a.x-b.x,a.y-b.y);if(pinchDistance>0)camera.current=zoomCamera(camera.current,distance/pinchDistance);camera.current.panX+=dx/2;camera.current.panY+=dy/2;pinchDistance=distance;}
      else if(e.shiftKey||e.buttons===2){camera.current.panX+=dx;camera.current.panY+=dy;}
      else{camera.current.yaw+=dx*.008;camera.current.pitch=clamp(camera.current.pitch+dy*.007,-1.3,1.3);}request();
    };
    const up=(e:PointerEvent)=>{pointers.delete(e.pointerId);if(!pointers.size)el.classList.remove('is-dragging');};
    const wheel=(e:WheelEvent)=>{e.preventDefault();if(e.ctrlKey||e.metaKey||e.deltaMode!==0)camera.current=zoomCamera(camera.current,Math.exp(-e.deltaY*(e.deltaMode===1?.04:.009)));else{camera.current.panX-=e.deltaX;camera.current.panY-=e.deltaY;}request();};
    const key=(e:KeyboardEvent)=>{if(e.target!==el||!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','+','=','-','Home'].includes(e.key))return;e.preventDefault();if(e.key==='Home')camera.current={...INITIAL_CAMERA};else if(['+','=','-'].includes(e.key))camera.current=zoomCamera(camera.current,e.key==='-'?.85:1.18);else if(e.shiftKey){camera.current.panX+=e.key==='ArrowLeft'?-25:e.key==='ArrowRight'?25:0;camera.current.panY+=e.key==='ArrowUp'?-25:e.key==='ArrowDown'?25:0;}else{camera.current.yaw+=e.key==='ArrowLeft'?-.12:e.key==='ArrowRight'?.12:0;camera.current.pitch=clamp(camera.current.pitch+(e.key==='ArrowUp'?-.1:e.key==='ArrowDown'?.1:0),-1.3,1.3);}request();};
    el.addEventListener('pointerdown',down);el.addEventListener('pointermove',move);el.addEventListener('pointerup',up);el.addEventListener('pointercancel',up);el.addEventListener('wheel',wheel,{passive:false});el.addEventListener('keydown',key);
    return()=>{observer.disconnect();cancelAnimationFrame(frame);el.removeEventListener('pointerdown',down);el.removeEventListener('pointermove',move);el.removeEventListener('pointerup',up);el.removeEventListener('pointercancel',up);el.removeEventListener('wheel',wheel);el.removeEventListener('keydown',key);};
  },[]);
  useEffect(()=>{paint.current();},[graph,selected]);
  function zoomBy(factor:number){camera.current=zoomCamera(camera.current,factor);paint.current();}
  return <div className="brain-stage" ref={viewport} tabIndex={0} role="group" aria-label="Interactive 3D brain map. Drag to rotate, shift-drag or two-finger scroll to pan, pinch to zoom. Arrow keys rotate; plus and minus zoom; Home resets." onContextMenu={e=>e.preventDefault()} onDoubleClick={()=>{camera.current={...INITIAL_CAMERA};paint.current();}} data-camera-zoom={zoom}>
    <canvas ref={canvas} aria-hidden="true"/><div className="brain-overlays">
      {edges.map(p=>{const e=graph.edges.find(e=>e.source+'/'+e.target===p.id)!,a=graph.nodes.find(n=>n.id===e.source)!,b=graph.nodes.find(n=>n.id===e.target)!;return <button key={p.id} className="brain-edge-button" style={{left:p.x,top:p.y}} aria-label={`${a.label} and ${b.label}, mentioned together in ${e.shared_entry_count} entries`} onClick={event=>{if(event.detail===0||!dragged.current)onEdge(e);}}><span>{e.shared_entry_count}</span></button>;})}
      {overlays.map(p=>{
        const n=graph.nodes.find(n=>n.id===p.id);if(!n)return null;
        const open=pinned===n.id;
        const detailsId='neuron-details-'+n.id;
        const left=22+Math.max(125,Math.min((viewport.current?.clientWidth??500)-125,p.x))-p.x;
        return <div key={n.id} className={'brain-topic '+(selected===n.id?'selected ':'')+(open?'pinned':'')}
          style={{left:p.x,top:p.y,'--node-color':palette[n.id]||'#c1abff'} as CSSProperties}>
          <button className="brain-marker" aria-label={`${n.label}, ${n.count} of ${graph.analyzed_entries} analyzed entries. Open evidence.`}
            aria-expanded={open} aria-controls={detailsId} onClick={event=>{if(event.detail===0||!dragged.current){setPinned(n.id);onNode(n);}}}>
            <span className="brain-topic-target"/>
          </button>
          <div id={detailsId} className={'neuron-tooltip '+(p.y<270?'tooltip-below':'')} style={{left}} role="region" aria-label={`${n.label} details`}>
            <strong>{n.label}</strong>
            <small>{n.count} of {graph.analyzed_entries} analyzed entries · {n.share===null?'No entries':Math.round(n.share*100)+'%'}</small>
            {open?<><div className="neuron-source-heading">Source entries<button aria-label="Close neuron details" onClick={()=>setPinned(null)}>×</button></div>
              <div className="neuron-sources">{n.entry_ids.map((id,index)=>{
                const entry=entries.find(e=>e.id===id);
                return <button key={id} onClick={()=>{if(onOpenEntry)onOpenEntry(id);else onNode(n);}}>
                  <span>{entry?new Date(entry.entry_date+'T12:00:00').toLocaleDateString(undefined,{month:'short',day:'numeric',year:'numeric'}):`Source entry ${index+1}`} ↗</span>
                  {entry&&<small>{entry.text.slice(0,85)}{entry.text.length>85?'…':''}</small>}
                </button>;
              })}{!n.entry_ids.length&&<small>No entries in this period.</small>}</div></>:<span>Click to keep open and read source entries ↗</span>}
          </div>
        </div>;
      })}
    </div><span className="brain-orientation" aria-hidden="true">3D / PERSPECTIVE</span><div className="brain-instructions">Drag to rotate <span>·</span> Two-finger scroll to pan <span>·</span> Pinch to zoom</div>
    <div className="map-zoom"><button aria-label="Zoom out" disabled={zoom<=55} onClick={()=>zoomBy(.85)}>−</button><button aria-label="Reset brain view" onClick={()=>{camera.current={...INITIAL_CAMERA};paint.current();}}>{zoom}%</button><button aria-label="Zoom in" disabled={zoom>=350} onClick={()=>zoomBy(1.18)}>+</button></div>
  </div>;
}
export function NeuronMap(props:Props){
  const{graph,onNode,compact=false}=props,[view,setView]=useState<'map'|'list'>('map');
  return <div className={'map-shell '+(compact?'compact':'')}><div className="map-toolbar"><span className="map-context"><span className="live-dot"/> YOUR THOUGHTS, CONNECTED</span><div className="map-switch" aria-label="Map display"><button aria-pressed={view==='map'} onClick={()=>setView('map')}><Icon name="map" size={15}/>3D Map</button><button aria-pressed={view==='list'} onClick={()=>setView('list')}><Icon name="book" size={15}/>List</button></div></div>
    {view==='map'?<BrainScene {...props}/>:<div className="map-list"><table><caption className="sr-only">Topic counts and shares of analyzed entries</caption><thead><tr><th>Topic</th><th>Entries</th><th>Share</th></tr></thead><tbody>{graph.nodes.map(n=><tr key={n.id}><td><button onClick={()=>onNode(n)}><span className="topic-dot" style={{background:palette[n.id]}}/>{n.label}</button></td><td>{n.count}</td><td>{n.share===null?'No entries':Math.round(n.share*100)+'%'}</td></tr>)}</tbody></table></div>}
    <div className="map-footer"><span><span className="legend-glow"/> Brighter means more entries</span><span>Connections mean mentioned together</span></div>{graph.total_entries===0&&<p className="map-empty">No entries in this period. Topic positions are preserved.</p>}
  </div>;
}
