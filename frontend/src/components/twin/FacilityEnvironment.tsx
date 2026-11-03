"use client";

import { memo, useEffect, useMemo } from 'react';
import { Line, RoundedBox } from '@react-three/drei';
import * as THREE from 'three';
import { labelTexture } from './textures';
import { Building } from './Building';
import { Racking } from './Racking';
import { Equipment } from './Equipment';
import { Features } from './Actors';
import { CleanroomShell } from './CleanroomShell';

export function Box({ position, size, color = '#e4eaeb', metalness = .05, roughness = .45, ...rest }: any) {
  return <mesh position={position} castShadow receiveShadow {...rest}><boxGeometry args={size}/><meshStandardMaterial color={color} metalness={metalness} roughness={roughness}/></mesh>;
}

export function Cylinder({ position, radius = .15, height = .4, color = '#b4bfc6', metalness = .65, ...rest }: any) {
  return <mesh position={position} castShadow receiveShadow {...rest}><cylinderGeometry args={[radius, radius, height, 16]}/><meshStandardMaterial color={color} metalness={metalness} roughness={.28}/></mesh>;
}

function Sign({ text, sub, position, rotation, floor = false, width = 3.3 }: any) {
  const texture = useMemo(() => labelTexture(text, {bg: floor ? '#e5edef' : '#21483e', fg: floor ? '#48616a' : '#eef6f2', sub, w:512,h:128, font:`600 ${Math.min(64,Math.floor(720/Math.max(String(text).length,1)))}px Arial`}), [text,sub,floor]);
  useEffect(() => () => texture.dispose(), [texture]);
  return <mesh position={position} rotation={rotation || (floor ? [-Math.PI/2,0,0] : [0,0,0])}><planeGeometry args={[width,width/4]}/><meshBasicMaterial map={texture} transparent side={THREE.DoubleSide} polygonOffset polygonOffsetFactor={-1}/></mesh>;
}

function Screen({ position, width = .5 }: any) {
  return <group position={position}><Box position={[0,0,0]} size={[width,.36,.055]} color="#273b48"/><Box position={[0,0,.031]} size={[width-.06,.29,.006]} color="#153c4e"/>{[0,1,2].map(i=><Box key={i} position={[-width*.12,.08-i*.075,.038]} size={[width*(.28+i*.1),.012,.006]} color={i===0?'#8ab9c6':'#4e8090'}/>)}<Box position={[0,-.24,-.02]} size={[.045,.14,.05]} color="#7c929c"/><Box position={[0,-.32,0]} size={[width*.6,.025,.2]} color="#94a5ac"/></group>;
}

function Bench({ rack }: any) {
  const w=rack.x2-rack.x1, d=rack.depth || 1, x=(rack.x1+rack.x2)/2, z=-rack.y-d/2;
  const kind = String(rack.id || '');
  const cold = kind.startsWith('cold'), gown = kind.startsWith('gowning');
  if (cold || gown) return <group position={[x,0,z]}>
    <Box position={[0,.08,0]} size={[w-.12,.16,d-.12]} color="#5d7079"/>
    <Box position={[0,1.06,0]} size={[w-.06,1.96,d-.06]} color={cold?'#cedce2':'#e1e8e9'}/>
    {[-1,1].map(side=><group key={side} position={[side*w/2,0,0]}>{Array.from({length:Math.max(1,Math.floor(d))},(_,i)=><group key={i} position={[0,0,-d/2+.5+i]}><Box position={[0,1.08,0]} size={[.045,1.8,.93]} color={cold?'#c5d3da':'#dce4e5'}/><Box position={[side*.04,1.18,.29]} size={[.05,.32,.035]} color="#71858e"/>{cold && <Box position={[side*.045,1.63,0]} size={[.012,.14,.25]} color="#38596a"/>}</group>)}</group>)}
    <Box position={[0,2.08,0]} size={[w+.02,.08,d+.02]} color="#f1f4f5"/>
    <Sign text={cold?'TEMPERATURE STORAGE':'GOWNING STORAGE'} position={[0,1.7,d/2+.03]} width={w*.83}/>
  </group>;
  return <group position={[x,0,z]}>
    <Box position={[0,.08,0]} size={[w-.16,.15,d-.16]} color="#5d7078"/>
    <Box position={[0,.47,0]} size={[w-.08,.78,d-.08]} color="#e2e9eb"/>
    <Box position={[0,.9,0]} size={[w+.03,.085,d+.03]} color="#9eb1b9" metalness={.7} roughness={.23}/>
    {[-1,1].map(side=><group key={side}>{Array.from({length:Math.max(1,Math.floor(d))},(_,i)=><group key={i} position={[side*w/2,.48,-d/2+.5+i]}><Box position={[0,0,0]} size={[.028,.66,.93]} color="#d6e1e5"/><Box position={[side*.025,.22,0]} size={[.04,.025,.33]} color="#71858e" metalness={.8}/></group>)}</group>)}
    {kind.startsWith('formulation') ? [-.85,.85].map((offset,i)=><group key={i} position={[0,0,offset]}><Cylinder position={[0,1.43,0]} radius={.56} height={.9}/><mesh position={[0,1.9,0]} castShadow><sphereGeometry args={[.56,20,12,0,Math.PI*2,0,Math.PI/2]}/><meshStandardMaterial color="#aebec5" metalness={.8} roughness={.25}/></mesh><Cylinder position={[0,2.1,0]} radius={.09} height={.3}/><Box position={[0,2.3,0]} size={[.32,.2,.24]} color="#597983"/>{[-.4,.4].map(leg=><Cylinder key={leg} position={[leg,1,0]} radius={.035} height={.3}/>)}<Cylinder position={[.58,1.3,.3]} radius={.035} height={.55}/></group>) : kind.startsWith('packaging') ? <>
      <Box position={[0,1.04,0]} size={[w-.3,.17,d-.3]} color="#526773"/>
      {Array.from({length:11},(_,i)=><Cylinder key={i} position={[0,1.15,-d/2+.32+i*(d-.64)/10]} radius={.055} height={w-.45} rotation={[0,0,Math.PI/2]}/>)}
      {[-.75,.65].map((offset,i)=><Box key={i} position={[0,1.39,offset]} size={[.65,.42,.55]} color={i?'#e0d4bc':'#d3c7af'}/>)}
    </> : <>
      <RoundedBox position={[0,1.25,-.8]} args={[w*.62,.58,.7]} radius={.045} smoothness={2} castShadow><meshStandardMaterial color="#edf2f3" roughness={.3}/></RoundedBox>
      <Screen position={[0,1.55,-.43]} width={w*.4}/>
      {kind.startsWith('research') ? <group position={[0,1,.65]}><Box position={[0,.04,0]} size={[.5,.06,.4]} color="#e1e9eb"/><Box position={[-.15,.32,0]} size={[.07,.6,.08]} color="#a1b2b9"/><Cylinder position={[0,.55,0]} radius={.07} height={.3} rotation={[0,0,-.45]} color="#344e5c"/><Box position={[0,.25,0]} size={[.42,.04,.3]} color="#3d515e"/></group> : <group position={[0,.98,.65]}><Box position={[0,.03,0]} size={[.65,.05,.42]} color="#9aacb5"/>{[-.2,0,.2].map(v=><group key={v}><Cylinder position={[v,.14,0]} radius={.045} height={.2} color="#d8edf0" metalness={.1}/><Cylinder position={[v,.25,0]} radius={.05} height={.035} color="#67869c"/></group>)}</group>}
    </>}
  </group>;
}

function Partition({ rack }: any) {
  const w=rack.x2-rack.x1, d=rack.depth||.18, x=(rack.x1+rack.x2)/2,z=-rack.y-d/2;
  const horizontal=w>d, length=horizontal?w:d, segments=Math.max(1,Math.ceil(length/2.5));
  return <group position={[x,0,z]} name={`facility-partition-${rack.id}`}>
    <Box position={[0,.12,0]} size={[w,.24,d]} color="#617d74" metalness={.3}/>
    <Box position={[0,.5,0]} size={[w,.76,d*.9]} color="#dbe2dc"/>
    <mesh position={[0,1.91,0]} rotation={[0,horizontal?0:Math.PI/2,0]} renderOrder={1}><planeGeometry args={[length-.12,2.04]}/><meshPhysicalMaterial color="#91b4af" transparent opacity={.34} roughness={.18} metalness={.1} side={THREE.DoubleSide} depthWrite={false} polygonOffset polygonOffsetFactor={1} polygonOffsetUnits={1}/></mesh>
    <Box position={[0,3.1,0]} size={[w,.32,d*.8]} color="#c6d3cc"/>
    {Array.from({length:segments+1},(_,i)=><Box key={i} position={[horizontal?-w/2+.045+(w-.09)*i/segments:0,1.65,horizontal?0:-d/2+.045+(d-.09)*i/segments]} size={horizontal?[.09,3.3,d]:[w,3.3,.09]} color="#68877b" metalness={.45}/>)}
    {[.9,2.25].map(height=><Box key={height} position={[0,height,0]} size={[w,.065,d*.8]} color="#89a294" metalness={.35}/>)}
    {/* Etched visibility band makes the glass legible from both sides. */}
    <Box position={[0,1.48,0]} size={horizontal?[w-.12,.09,d*.55]:[w*.55,.09,d-.12]} color="#d8e9df"/>
  </group>;
}

function Entrances({ world }: any) {
  const rows = new Map<number, any[]>();
  for (const rack of world.racks || []) {
    if (rack.kind !== 'partition' || rack.x2-rack.x1 < (rack.depth || .18)) continue;
    if (!rows.has(rack.y)) rows.set(rack.y, []);
    rows.get(rack.y)!.push(rack);
  }
  const openings: any[] = [];
  for (const [y, row] of rows) {
    row.sort((a,b)=>a.x1-b.x1);
    for (let i=1;i<row.length;i++) {
      const left=row[i-1], right=row[i], width=right.x1-left.x2;
      if (width < 2 || width > 5) continue;
      const x=(left.x2+right.x1)/2;
      const room=(world.features || []).filter((f:any)=>f.type==='room').sort((a:any,b:any)=>Math.hypot(a.x-x,a.y-y)-Math.hypot(b.x-x,b.y-y))[0];
      openings.push({x,y,width,label:room?.label || 'Transfer access'});
    }
  }
  return <>{openings.map(door=><group key={`${door.x}-${door.y}`} position={[door.x,0,-door.y-.09]} name={`facility-open-entrance-${door.x}-${door.y}`}>
    {/* Header only: the existing opening stays completely unobstructed. */}
    <Box position={[0,3.08,0]} size={[door.width,.44,.18]} color="#718d7c"/>
    <Box position={[0,2.83,0]} size={[door.width,.06,.18]} color="#d8e3db"/>
    <Sign text={door.label.toUpperCase()} position={[0,3.12,.105]} width={Math.min(door.width-.25,3.4)}/>
    <Sign text={door.label.toUpperCase()} position={[0,3.12,-.105]} rotation={[0,Math.PI,0]} width={Math.min(door.width-.25,3.4)}/>
  </group>)}</>;
}

function Floor({ world }: any) {
  const g=world.geofence,sx=g.max_x-g.min_x,sy=g.max_y-g.min_y,cx=(g.min_x+g.max_x)/2,cy=(g.min_y+g.max_y)/2;
  const corridor=world.zones?.find((z:any)=>z.name==='corridor')?.rect;
  const texture=useMemo(()=>{
    const canvas=document.createElement('canvas');canvas.width=512;canvas.height=512;
    const ctx=canvas.getContext('2d')!;ctx.fillStyle='#d3dde0';ctx.fillRect(0,0,512,512);
    ctx.strokeStyle='#aabac0';ctx.lineWidth=2;ctx.strokeRect(0,0,512,512);
    for(let i=0;i<1800;i++){const x=(i*73)%512,y=(i*137)%512;ctx.fillStyle=i%2?'#ffffff0c':'#61798508';ctx.fillRect(x,y,2,2);}
    const t=new THREE.CanvasTexture(canvas);t.wrapS=t.wrapT=THREE.RepeatWrapping;t.repeat.set(sx/2,sy/2);t.colorSpace=THREE.SRGBColorSpace;return t;
  },[sx,sy]);
  useEffect(()=>()=>texture.dispose(),[texture]);
  return <>
    <Box position={[cx,-.18,-cy]} size={[sx+.35,.35,sy+.35]} color="#748a94"/>
    <mesh rotation={[-Math.PI/2,0,0]} position={[cx,.006,-cy]} receiveShadow><planeGeometry args={[sx,sy]}/><meshStandardMaterial map={texture} roughness={.36} metalness={.13}/></mesh>
    {(world.features||[]).filter((f:any)=>f.type==='room').map((f:any)=><group key={f.id}><mesh rotation={[-Math.PI/2,0,0]} position={[f.x,.012,-f.y]} receiveShadow><planeGeometry args={[f.width,f.depth]}/><meshStandardMaterial color={f.tone||'#dce7e9'} roughness={.5} transparent opacity={.3} depthWrite={false}/></mesh><Sign floor text={String(f.label).toUpperCase()} position={[f.x,.025,-(f.y>cy?f.y-3.1:f.y+3.1)]} width={4.2}/></group>)}
    {corridor&&[corridor.min_y+.15,corridor.max_y-.15].map(y=><Line key={y} points={[[corridor.min_x+.5,.035,-y],[corridor.max_x-.5,.035,-y]]} color="#b5a34f" lineWidth={1.5} dashed dashSize={.6} gapSize={.18}/>)}
    {corridor&&<Sign floor text="SHARED TRANSFER CORRIDOR" position={[(corridor.min_x+corridor.max_x)/2,.03,-(corridor.min_y+corridor.max_y)/2]} width={8}/>}
  </>;
}


// Both operational views render the same static geometry from /sim/world.
// Choosing a renderer must never choose or synthesize a different site layout.
export const FacilityEnvironment = memo(function FacilityEnvironment({ world, roofMode = "auto" }: { world: any; roofMode?: "auto" | "show" | "hide" }) {
  const cleanroom = (world.racks || []).some((rack: any) => rack.kind === 'partition' || rack.kind === 'bench');
  if (!cleanroom) return <group name="facility-environment">
    <Building world={world}/>
    <Racking racks={(world.racks || []).filter((rack: any) => !rack.kind || rack.kind === 'rack')}/>
    <Equipment items={world.racks || []}/>
    <Features features={world.features || []}/>
  </group>;
  return <group name="facility-environment">
    <Floor world={world}/>
    <CleanroomShell world={world} roofMode={roofMode}/>
    <Entrances world={world}/>
    {(world.racks || []).map((rack: any, i: number) => rack.kind === 'partition'
      ? <Partition key={rack.id || i} rack={rack}/>
      : <Bench key={rack.id || i} rack={rack}/>)}
    {(world.bays || []).map((bay: any) => <group key={bay.id}>
      <mesh position={[bay.x,.035,-bay.y]} rotation={[-Math.PI/2,0,0]}>
        <ringGeometry args={[.69,.74,32]}/><meshBasicMaterial color="#7d9ba6"/>
      </mesh>
      <Sign floor text={bay.id} position={[bay.x,.03,-bay.y]} width={.9}/>
    </group>)}
  </group>;
});
