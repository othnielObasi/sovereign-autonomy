'use client';

import React, { useRef, useEffect, useState, useCallback } from 'react';

interface Position {
  x: number;
  y: number;
}

interface Human {
  id: string;
  x: number;
  y: number;
  distance?: number;
}

interface Obstacle {
  id: string;
  x: number;
  y: number;
  radius: number;
}

interface MapProps {
  robotPosition: Position;
  targetPosition?: Position;
  humans?: Human[];
  obstacles?: Obstacle[];
  riskScore?: number;
  safetyStatus?: 'SAFE' | 'SLOW' | 'STOP' | 'REPLAN';
  width?: number;
  height?: number;
  showHeatmap?: boolean;
  showTrail?: boolean;
}

const GRID_SIZE = 10;
const ROBOT_RADIUS = 12;
const HUMAN_RADIUS = 10;

export default function Map2DEnhanced({
  robotPosition,
  targetPosition,
  humans = [],
  obstacles = [],
  riskScore = 0,
  safetyStatus = 'SAFE',
  width = 600,
  height = 400,
  showHeatmap = true,
  showTrail = true,
}: MapProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [isPanning, setIsPanning] = useState(false);
  const [lastPanPoint, setLastPanPoint] = useState({ x: 0, y: 0 });
  const [trail, setTrail] = useState<Position[]>([]);
  const [pulsePhase, setPulsePhase] = useState(0);

  // Update trail
  useEffect(() => {
    if (showTrail && robotPosition) {
      setTrail(prev => {
        const newTrail = [...prev, { ...robotPosition }];
        return newTrail.slice(-50); // Keep last 50 positions
      });
    }
  }, [robotPosition.x, robotPosition.y, showTrail]);

  // Animation loop for pulsing
  useEffect(() => {
    const interval = setInterval(() => {
      setPulsePhase(p => (p + 0.1) % (Math.PI * 2));
    }, 50);
    return () => clearInterval(interval);
  }, []);

  // Handle mouse wheel zoom
  const handleWheel = useCallback((e: React.WheelEvent) => {
    e.preventDefault();
    const delta = e.deltaY > 0 ? 0.9 : 1.1;
    setZoom(z => Math.max(0.5, Math.min(3, z * delta)));
  }, []);

  // Handle pan
  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    if (e.shiftKey) {
      setIsPanning(true);
      setLastPanPoint({ x: e.clientX, y: e.clientY });
    }
  }, []);

  const handleMouseMove = useCallback((e: React.MouseEvent) => {
    if (isPanning) {
      const dx = e.clientX - lastPanPoint.x;
      const dy = e.clientY - lastPanPoint.y;
      setPan(p => ({ x: p.x + dx, y: p.y + dy }));
      setLastPanPoint({ x: e.clientX, y: e.clientY });
    }
  }, [isPanning, lastPanPoint]);

  const handleMouseUp = useCallback(() => {
    setIsPanning(false);
  }, []);

  // Draw canvas
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    // Clear
    ctx.fillStyle = '#0D1B2A';
    ctx.fillRect(0, 0, width, height);

    // Apply transform
    ctx.save();
    ctx.translate(width / 2 + pan.x, height / 2 + pan.y);
    ctx.scale(zoom, zoom);
    ctx.translate(-width / 2, -height / 2);

    // Draw grid
    ctx.strokeStyle = 'rgba(0, 212, 255, 0.1)';
    ctx.lineWidth = 1;
    for (let x = 0; x <= width; x += GRID_SIZE * 4) {
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, height);
      ctx.stroke();
    }
    for (let y = 0; y <= height; y += GRID_SIZE * 4) {
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(width, y);
      ctx.stroke();
    }

    // Draw heatmap
    if (showHeatmap) {
      const gridW = Math.ceil(width / GRID_SIZE);
      const gridH = Math.ceil(height / GRID_SIZE);
      
      for (let gx = 0; gx < gridW; gx++) {
        for (let gy = 0; gy < gridH; gy++) {
          const cellX = gx * GRID_SIZE + GRID_SIZE / 2;
          const cellY = gy * GRID_SIZE + GRID_SIZE / 2;
          
          let maxRisk = 0;
          
          // Risk from humans
          humans.forEach(h => {
            const hx = (h.x / 100) * width;
            const hy = (h.y / 100) * height;
            const dist = Math.sqrt(Math.pow(cellX - hx, 2) + Math.pow(cellY - hy, 2));
            const risk = Math.max(0, 1 - dist / 100);
            maxRisk = Math.max(maxRisk, risk);
          });
          
          // Risk from obstacles
          obstacles.forEach(o => {
            const ox = (o.x / 100) * width;
            const oy = (o.y / 100) * height;
            const dist = Math.sqrt(Math.pow(cellX - ox, 2) + Math.pow(cellY - oy, 2));
            const risk = Math.max(0, 1 - dist / 80);
            maxRisk = Math.max(maxRisk, risk * 0.7);
          });
          
          if (maxRisk > 0.1) {
            const r = Math.floor(255 * maxRisk);
            const g = Math.floor(255 * (1 - maxRisk) * 0.5);
            ctx.fillStyle = `rgba(${r}, ${g}, 0, ${maxRisk * 0.3})`;
            ctx.fillRect(gx * GRID_SIZE, gy * GRID_SIZE, GRID_SIZE, GRID_SIZE);
          }
        }
      }
    }

    // Draw trail
    if (showTrail && trail.length > 1) {
      trail.forEach((pos, i) => {
        const alpha = (i / trail.length) * 0.5;
        const x = (pos.x / 100) * width;
        const y = (pos.y / 100) * height;
        
        ctx.beginPath();
        ctx.arc(x, y, 3, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(0, 212, 255, ${alpha})`;
        ctx.fill();
      });
    }

    // Draw obstacles
    obstacles.forEach(o => {
      const x = (o.x / 100) * width;
      const y = (o.y / 100) * height;
      ctx.beginPath();
      ctx.arc(x, y, o.radius, 0, Math.PI * 2);
      ctx.fillStyle = 'rgba(100, 100, 100, 0.8)';
      ctx.fill();
      ctx.strokeStyle = '#666';
      ctx.lineWidth = 2;
      ctx.stroke();
    });

    // Draw target
    if (targetPosition) {
      const tx = (targetPosition.x / 100) * width;
      const ty = (targetPosition.y / 100) * height;
      ctx.beginPath();
      ctx.arc(tx, ty, 8, 0, Math.PI * 2);
      ctx.strokeStyle = '#22c55e';
      ctx.lineWidth = 2;
      ctx.setLineDash([4, 4]);
      ctx.stroke();
      ctx.setLineDash([]);
      
      // Target cross
      ctx.beginPath();
      ctx.moveTo(tx - 12, ty);
      ctx.lineTo(tx + 12, ty);
      ctx.moveTo(tx, ty - 12);
      ctx.lineTo(tx, ty + 12);
      ctx.strokeStyle = '#22c55e';
      ctx.lineWidth = 1;
      ctx.stroke();
    }

    // Draw humans
    humans.forEach(h => {
      const hx = (h.x / 100) * width;
      const hy = (h.y / 100) * height;
      
      // Danger radius
      ctx.beginPath();
      ctx.arc(hx, hy, 30, 0, Math.PI * 2);
      ctx.strokeStyle = 'rgba(239, 68, 68, 0.3)';
      ctx.lineWidth = 1;
      ctx.stroke();
      
      // Human circle
      ctx.beginPath();
      ctx.arc(hx, hy, HUMAN_RADIUS, 0, Math.PI * 2);
      ctx.fillStyle = '#f97316';
      ctx.fill();
      
      // Human icon
      ctx.fillStyle = 'white';
      ctx.font = '10px sans-serif';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText('👤', hx, hy);
    });

    // Draw robot
    const rx = (robotPosition.x / 100) * width;
    const ry = (robotPosition.y / 100) * height;
    
    // Robot glow
    const gradient = ctx.createRadialGradient(rx, ry, 0, rx, ry, ROBOT_RADIUS * 2);
    gradient.addColorStop(0, 'rgba(0, 212, 255, 0.3)');
    gradient.addColorStop(1, 'rgba(0, 212, 255, 0)');
    ctx.fillStyle = gradient;
    ctx.beginPath();
    ctx.arc(rx, ry, ROBOT_RADIUS * 2, 0, Math.PI * 2);
    ctx.fill();
    
    // Robot body
    ctx.beginPath();
    ctx.arc(rx, ry, ROBOT_RADIUS, 0, Math.PI * 2);
    ctx.fillStyle = '#00D4FF';
    ctx.fill();
    ctx.strokeStyle = '#0A1929';
    ctx.lineWidth = 2;
    ctx.stroke();
    
    // Robot label
    ctx.fillStyle = '#0A1929';
    ctx.font = 'bold 10px sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText('R1', rx, ry);

    // Draw safety status badge
    const statusColors: Record<string, string> = {
      SAFE: '#22c55e',
      SLOW: '#eab308',
      STOP: '#ef4444',
      REPLAN: '#3b82f6',
    };
    
    const badgeY = ry - ROBOT_RADIUS - 20;
    const pulseScale = safetyStatus === 'STOP' ? 1 + Math.sin(pulsePhase) * 0.1 : 1;
    
    ctx.save();
    ctx.translate(rx, badgeY);
    ctx.scale(pulseScale, pulseScale);
    
    ctx.fillStyle = statusColors[safetyStatus] || '#666';
    ctx.beginPath();
    ctx.roundRect(-25, -10, 50, 20, 4);
    ctx.fill();
    
    ctx.fillStyle = safetyStatus === 'SLOW' ? '#000' : '#fff';
    ctx.font = 'bold 11px sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(safetyStatus, 0, 0);
    
    ctx.restore();

    ctx.restore();
  }, [robotPosition, targetPosition, humans, obstacles, zoom, pan, trail, showHeatmap, showTrail, pulsePhase, safetyStatus, width, height]);

  return (
    <div className="relative">
      <canvas
        ref={canvasRef}
        width={width}
        height={height}
        onWheel={handleWheel}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseUp}
        className="rounded-lg border border-slate-700 cursor-crosshair"
        style={{ cursor: isPanning ? 'grabbing' : 'crosshair' }}
      />
      
      {/* Controls */}
      <div className="absolute top-2 right-2 flex gap-1">
        <button
          onClick={() => setZoom(z => Math.min(3, z * 1.2))}
          className="w-8 h-8 bg-slate-800/80 rounded text-white hover:bg-slate-700"
        >
          +
        </button>
        <button
          onClick={() => setZoom(z => Math.max(0.5, z / 1.2))}
          className="w-8 h-8 bg-slate-800/80 rounded text-white hover:bg-slate-700"
        >
          −
        </button>
        <button
          onClick={() => { setZoom(1); setPan({ x: 0, y: 0 }); }}
          className="w-8 h-8 bg-slate-800/80 rounded text-white hover:bg-slate-700 text-xs"
        >
          ⟲
        </button>
      </div>
      
      {/* Legend */}
      <div className="absolute bottom-2 left-2 flex gap-3 text-xs bg-slate-900/80 px-2 py-1 rounded">
        <span className="text-slate-400">Scroll: zoom</span>
        <span className="text-slate-400">Shift+drag: pan</span>
      </div>
    </div>
  );
}
