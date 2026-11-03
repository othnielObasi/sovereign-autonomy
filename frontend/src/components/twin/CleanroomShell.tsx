"use client";

import { useRef } from 'react';
import { useFrame } from '@react-three/fiber';
import * as THREE from 'three';

const HEIGHT = 3.4;

function Panel({ position, size, color = '#e5e9e6', ...props }: any) {
  return <mesh position={position} castShadow receiveShadow {...props}>
    <boxGeometry args={size}/><meshStandardMaterial color={color} roughness={.58} metalness={.08}/>
  </mesh>;
}

// The original warehouse uses this same camera-dependent cutaway principle.
// All four perimeter walls exist; the near walls yield to an outside camera.
function CutawayWall({ x, z, nx, nz, children }: any) {
  const group = useRef<THREE.Group>(null!);
  useFrame(({ camera }) => {
    if (group.current) {
      const distance = (camera.position.x - x) * nx + (camera.position.z - z) * nz;
      if (distance > .25) group.current.visible = true;
      else if (distance < -.25) group.current.visible = false;
    }
  });
  return <group ref={group} name={`facility-perimeter-wall-${nx}-${nz}`}>{children}</group>;
}

function Ceiling({ world, roofMode }: any) {
  const group = useRef<THREE.Group>(null!);
  const g = world.geofence;
  useFrame(({ camera }) => {
    if (!group.current) return;
    if (roofMode !== 'auto') group.current.visible = roofMode === 'show';
    else if (camera.position.y < HEIGHT-.15) group.current.visible = true;
    else if (camera.position.y > HEIGHT+.35) group.current.visible = false;
  });
  const width = g.max_x - g.min_x, depth = g.max_y - g.min_y;
  const cx = (g.min_x + g.max_x) / 2, cz = -(g.min_y + g.max_y) / 2;
  const rooms = (world.features || []).filter((f: any) => f.type === 'room');
  return <group ref={group} name="facility-ceiling">
    <Panel position={[cx,HEIGHT+.2,cz]} size={[width,.15,depth]} color="#d6ddd9"/>
    {/* Suspended grid, sealed lights and supply/extract panels at physical scale. */}
    {Array.from({ length: Math.ceil(width / 3) + 1 }, (_, i) => <Panel key={`x-${i}`} position={[g.min_x+i*3,HEIGHT+.08,cz]} size={[.035,.06,depth]} color="#a3b0ac"/>)}
    {Array.from({ length: Math.ceil(depth / 3) + 1 }, (_, i) => <Panel key={`z-${i}`} position={[cx,HEIGHT+.08,-g.min_y-i*3]} size={[width,.06,.035]} color="#a3b0ac"/>)}
    {rooms.map((room: any) => <group key={room.id}>
      <pointLight position={[room.x,HEIGHT-.23,-room.y]} color="#f2fff5" intensity={24} distance={11} decay={2}/>
      <Panel position={[room.x,HEIGHT-.04,-room.y]} size={[1.25,.08,2.5]} color="#8a9b98"/>
      <mesh position={[room.x,HEIGHT-.09,-room.y]} rotation={[Math.PI/2,0,0]}>
        <planeGeometry args={[1.12,2.35]}/><meshStandardMaterial color="#f4fff9" emissive="#e4f7ed" emissiveIntensity={1.5}/>
      </mesh>
      <Panel position={[room.x+2.8,HEIGHT-.02,-room.y]} size={[.9,.1,.9]} color="#c4ceca"/>
      {Array.from({length: 6}, (_, i) => <Panel key={i} position={[room.x+2.8,HEIGHT-.08,-room.y-.32+i*.13]} size={[.72,.025,.035]} color="#6b8079"/>)}
    </group>)}
    <Panel position={[cx,HEIGHT-.17,cz]} size={[width,.3,.6]} color="#b4c2bd"/>
  </group>;
}

/** Finishes sit on the existing geofence; no new floor obstacles or closed doors. */
export function CleanroomShell({ world, roofMode = "auto" }: any) {
  const g = world.geofence;
  const width = g.max_x-g.min_x, depth = g.max_y-g.min_y;
  const cx = (g.min_x+g.max_x)/2, cz = -(g.min_y+g.max_y)/2;
  return <group name="facility-shell">
    {[
      {x:g.min_x,z:cz,nx:1,nz:0,length:depth,rotation:Math.PI/2},
      {x:g.max_x,z:cz,nx:-1,nz:0,length:depth,rotation:Math.PI/2},
      {x:cx,z:-g.min_y,nx:0,nz:-1,length:width,rotation:0},
      {x:cx,z:-g.max_y,nx:0,nz:1,length:width,rotation:0},
    ].map((wall,i) => <CutawayWall key={i} {...wall}>
      <group position={[wall.x,0,wall.z]} rotation={[0,wall.rotation,0]}>
        <Panel position={[0,HEIGHT/2,0]} size={[wall.length,HEIGHT,.18]}/>
        <Panel position={[0,.14,0]} size={[wall.length,.28,.21]} color="#7e9690"/>
        <Panel position={[0,.95,0]} size={[wall.length,.08,.23]} color="#bdccc5"/>
        <Panel position={[0,HEIGHT-.07,0]} size={[wall.length,.14,.24]} color="#80988e"/>
        {Array.from({length:Math.floor(wall.length/3)},(_,j)=><Panel key={j} position={[-wall.length/2+(j+1)*3,HEIGHT/2,.101]} size={[.016,HEIGHT-.3,.008]} color="#afbeb6"/>)}
      </group>
    </CutawayWall>)}
    <Ceiling world={world} roofMode={roofMode}/>
  </group>;
}
