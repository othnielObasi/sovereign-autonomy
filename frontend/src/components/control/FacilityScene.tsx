"use client";

import { useEffect, useMemo, useRef, useState } from 'react';
import { Canvas, useFrame, useThree } from '@react-three/fiber';
import { Html, Line, OrbitControls } from '@react-three/drei';
import * as THREE from 'three';
import { FleetRobot, Forklift } from '@/components/twin/Actors';
import { FacilityEnvironment, Box, Cylinder } from '@/components/twin/FacilityEnvironment';
import { cameraObstacles, clearFollowCamera } from '@/components/twin/cameraGeometry';

type CameraMode = 'overview' | 'follow' | 'robot';
type Pose = { x: number; y: number; theta: number };

// Demand rendering gives the scene a bounded cadence, including on software GPUs.
// Interpolation only approaches received poses: it never predicts robot movement.
function RenderCadence({ live, software }: { live: boolean; software: boolean }) {
  const { invalidate, gl } = useThree();
  useEffect(() => {
    let visible = true;
    const observer = new IntersectionObserver(entries => { visible = entries[0].isIntersecting; });
    observer.observe(gl.domElement);
    let frames = 0;
    const timer = setInterval(() => {
      if (visible && !document.hidden) {
        if (software && ++frames % 5 === 0) gl.shadowMap.needsUpdate = true;
        invalidate();
      }
    }, live ? software ? 200 : 50 : 500);
    return () => { clearInterval(timer); observer.disconnect(); };
  }, [invalidate, gl, live, software]);
  return null;
}

function CameraRig({ mode, world, pose, eyeHeight }: { eyeHeight: number; mode: CameraMode; world: any; pose: React.MutableRefObject<Pose> }) {
  const { camera, size, invalidate } = useThree();
  const g = world.geofence;
  const cx = (g.min_x + g.max_x) / 2, cy = (g.min_y + g.max_y) / 2;
  const span = Math.max(g.max_x - g.min_x, g.max_y - g.min_y);
  const desired = useMemo(() => new THREE.Vector3(), []);
  const look = useMemo(() => new THREE.Vector3(), []);
  const snap = useRef(true);
  const cameraBoxes = useMemo(() => cameraObstacles(world), [world]);
  useEffect(() => {
    const cam = camera as THREE.PerspectiveCamera;
    cam.fov = mode === 'robot' ? 76 : mode === 'follow' ? 56 : 43;
    cam.near = mode === 'robot' ? .04 : .1;
    cam.updateProjectionMatrix();
    snap.current = true;
    if (mode === 'overview') {
      const fit = Math.max(1, 1.45 / (size.width / size.height)) * 1.08;
      camera.position.set(cx + span * .6 * fit, span * .66 * fit, -cy + span * .6 * fit);
      camera.lookAt(cx, .5, -cy);
    }
    invalidate();
  }, [mode, camera, size.width, size.height, cx, cy, span, invalidate]);
  useFrame((_, dt) => {
    if (mode === 'overview') return;
    const r = pose.current, fx = Math.cos(r.theta), fz = -Math.sin(r.theta);
    if (mode === 'follow') {
      desired.set(r.x - fx * 3.8, 2.15, -r.y - fz * 3.8);
      look.set(r.x + fx * .8, .7, -r.y + fz * .8);
    } else {
      desired.set(r.x + fx * .45, eyeHeight, -r.y + fz * .45);
      look.set(r.x + fx * 8, eyeHeight-.05, -r.y + fz * 8);
    }
    camera.position.lerp(desired, snap.current ? 1 : 1 - Math.exp(-5 * Math.min(dt, .1)));
    if (mode === 'follow') {
      const safe = clearFollowCamera({x:r.x,y:.85,z:-r.y}, camera.position, cameraBoxes, g);
      camera.position.set(safe.x,safe.y,safe.z);
    }
    camera.lookAt(look); snap.current = false;
  });
  return null;
}

function Technician({ person }: any) {
  const group=useRef<THREE.Group>(null!), left=useRef<THREE.Group>(null!), right=useRef<THREE.Group>(null!);
  const phase=useRef(0), first=useRef(true);
  useFrame((_,dt)=>{
    const g=group.current;if(!g)return;
    const target=new THREE.Vector3(person.x,0,-person.y);
    if(first.current || g.position.distanceTo(target)>6){g.position.copy(target);first.current=false;}
    const before=g.position.clone();g.position.lerp(target,1-Math.exp(-7*Math.min(dt,.1)));
    const distance=g.position.distanceTo(before);phase.current+=distance*8;
    const heading=person.heading??0;g.rotation.y+=Math.atan2(Math.sin(heading-g.rotation.y),Math.cos(heading-g.rotation.y))*.25;
    const swing=distance>.0005?Math.sin(phase.current)*.32:0;
    if(left.current)left.current.rotation.x=swing;if(right.current)right.current.rotation.x=-swing;
  });
  return <group ref={group}>
    <mesh position={[0,1.08,0]} castShadow><capsuleGeometry args={[.18,.43,4,10]}/><meshStandardMaterial color="#e4edf0" roughness={.85}/></mesh>
    <mesh position={[0,1.66,0]} castShadow><sphereGeometry args={[.16,16,12]}/><meshStandardMaterial color="#e9eff0" roughness={.8}/></mesh>
    <Box position={[.115,1.64,0]} size={[.085,.12,.21]} color="#c8a48b"/><Box position={[.162,1.59,0]} size={[.04,.075,.2]} color="#a6cbd4"/>
    {[-1,1].map(side=><group key={side} position={[0,.79,side*.115]} ref={side===-1?left:right}><Cylinder position={[0,-.25,0]} radius={.075} height={.52} color="#dde7eb" metalness={0}/><Box position={[.04,-.56,0]} size={[.27,.12,.15]} color="#7a94a1"/></group>)}
    {[-1,1].map(side=><group key={side} position={[0,1.27,side*.23]} rotation={[side*.1,0,.1]}><Cylinder position={[0,-.19,0]} radius={.065} height={.4} color="#dce8ed" metalness={0}/><mesh position={[.02,-.42,0]}><sphereGeometry args={[.067,10,8]}/><meshStandardMaterial color="#a8cad6"/></mesh></group>)}
  </group>;
}

export default function FacilityScene({ world, telemetry, fleet, goal, path=[], selected, onSelect, live=true }: any) {
  const [mode,setMode]=useState<CameraMode>('overview');
  const [software,setSoftware]=useState(false);
  const container=useRef<HTMLDivElement>(null);
  const [fullscreen,setFullscreen]=useState(false), [screenError,setScreenError]=useState('');
  useEffect(()=>{
    const update=()=>setFullscreen(document.fullscreenElement===container.current);
    document.addEventListener('fullscreenchange',update);
    return ()=>document.removeEventListener('fullscreenchange',update);
  },[]);
  async function expand() {
    try { setScreenError(''); if(document.fullscreenElement===container.current) await document.exitFullscreen(); else await container.current?.requestFullscreen(); }
    catch { setScreenError('Fullscreen is unavailable in this browser.'); }
  }
  const robot=fleet.find((r:any)=>r.robot_id===selected)||fleet[0];
  const pose=useRef<Pose>({x:robot?.x||0,y:robot?.y||0,theta:robot?.theta||0});
  useEffect(()=>{if(robot)pose.current={x:robot.x,y:robot.y,theta:robot.theta||0};},[selected]);
  const g=world.geofence,cx=(g.min_x+g.max_x)/2,cy=(g.min_y+g.max_y)/2;
  const lightTarget=useMemo(()=>{const target=new THREE.Object3D();target.position.set(cx,0,-cy);return target;},[cx,cy]);
  const people=telemetry?.walking_humans||world.walking_humans||[];
  const obstacles=telemetry?.obstacles||world.obstacles||[];
  return <div ref={container} className="sa-real-scene">
    <Canvas frameloop="demand" shadows dpr={software?1:[1,1.35]} camera={{position:[cx+28,30,-cy+28],fov:43,near:.1,far:250}} gl={{antialias:true,powerPreference:'low-power'}} aria-label="Live perspective facility" onCreated={({gl})=>{
      gl.setClearColor('#cbd6dc');gl.toneMapping=THREE.ACESFilmicToneMapping;gl.toneMappingExposure=1.12;
      const context=gl.getContext(), extension=context.getExtension('WEBGL_debug_renderer_info');
      const renderer=extension?String(context.getParameter(extension.UNMASKED_RENDERER_WEBGL)):'';
      const reduced=/swiftshader|llvmpipe|software|microsoft basic/i.test(renderer);
      setSoftware(reduced);
      if(reduced){gl.shadowMap.autoUpdate=false;gl.shadowMap.needsUpdate=true;}
    }}>
      <ambientLight intensity={.4}/><hemisphereLight args={['#e7f4ff','#6c7c85',1.35]}/>
      <primitive object={lightTarget}/><directionalLight target={lightTarget} position={[cx+12,28,-cy+8]} intensity={3.2} color="#fff5e6" castShadow shadow-mapSize={software?[512,512]:[1024,1024]} shadow-camera-left={-27} shadow-camera-right={27} shadow-camera-top={25} shadow-camera-bottom={-25} shadow-camera-far={100} shadow-normalBias={.035} shadow-bias={-.00015}/>
      <directionalLight position={[cx-20,14,-cy-12]} intensity={.9} color="#b5d6ed"/>
      <RenderCadence live={live} software={software}/><CameraRig mode={mode} world={world} pose={pose} eyeHeight={robot?.robot_kind==='humanoid'?1.61:.85}/>
      {mode==='overview'&&<OrbitControls makeDefault target={[cx,.5,-cy]} enableDamping={false} minPolarAngle={.25} maxPolarAngle={Math.PI/2.15} minDistance={5} maxDistance={110}/>}
      <mesh rotation={[-Math.PI/2,0,0]} position={[cx,-.38,-cy]} receiveShadow><planeGeometry args={[240,240]}/><meshStandardMaterial color="#bbc9cf" roughness={.9}/></mesh>
      <FacilityEnvironment world={world}/>
      {goal&&Number.isFinite(goal.x)&&Number.isFinite(goal.y)&&<mesh position={[goal.x,.04,-goal.y]} rotation={[-Math.PI/2,0,0]}><ringGeometry args={[.69,.74,32]}/><meshBasicMaterial color="#608e3b"/></mesh>}
      {path.length>1&&<Line points={path.map((p:any)=>[p.x,.045,-p.y])} color="#66a668" lineWidth={3} dashed dashSize={.4} gapSize={.2}/>}
      {obstacles.filter((o:any)=>o.type!=='robot').map((o:any,i:number)=>o.type==='forklift'?<Forklift key={`forklift-${i}`} x={o.x} y={o.y} heading={o.heading||0}/>:o.type==='spill'?<mesh key={i} rotation={[-Math.PI/2,0,0]} position={[o.x,.04,-o.y]}><circleGeometry args={[o.r||.45,32]}/><meshPhysicalMaterial color="#b99841" transparent opacity={.65} roughness={.1}/></mesh>:<Box key={i} position={[o.x,.25,-o.y]} size={[(o.r||.4)*1.4,.5,(o.r||.4)*1.4]} color="#ad9876"/>)}
      {people.map((p:any,i:number)=><Technician key={p.name||p.id||i} person={p}/>)}
      {fleet.map((r:any)=><group key={r.robot_id} onClick={e=>{e.stopPropagation();onSelect(r.robot_id);}}>
        <FleetRobot robot_kind={r.robot_kind} x={r.x} y={r.y} theta={r.theta||0} verdict={r.estopped?'DENIED':r.speed>.01?'APPROVED':'IDLE'} pose={r.robot_id===selected?pose:undefined}/>
        {mode==='overview'&&<Html position={[r.x,r.robot_kind==='humanoid'?2.1:1.45,-r.y]} center><button className={`sa-scene-carrier-label ${selected===r.robot_id?'is-selected':''}`} onClick={()=>onSelect(r.robot_id)}>{r.robot_id}<span>{r.estopped?'Stopped':r.speed>.01?'Moving':'Standby'}</span></button></Html>}
      </group>)}
    </Canvas>
    <button className="sa-scene-expand" onClick={expand}>{fullscreen?'Exit fullscreen':'Expand facility'}</button>
    {screenError&&<span role="status" className="sa-scene-screen-error">{screenError}</span>}
    <div className="sa-scene-camera-controls" role="group" aria-label="Camera perspective">{([{id:'overview',label:'Overview'},{id:'follow',label:'Follow robot'},{id:'robot',label:'Robot eye'}] as const).map(m=><button key={m.id} aria-pressed={mode===m.id} disabled={!robot&&m.id!=='overview'} onClick={()=>setMode(m.id)}>{m.label}</button>)}</div>
  </div>;
}
