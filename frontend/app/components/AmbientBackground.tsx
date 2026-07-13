"use client";

import { useEffect, useRef } from "react";

export default function AmbientBackground() {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let animationId: number;
    let time = 0;

    function resize() {
      if (!canvas) return;
      canvas.width = window.innerWidth;
      canvas.height = window.innerHeight;
    }
    resize();
    window.addEventListener("resize", resize);

    const blobs = [
      { x: 0.4, y: 0.2, r: 0.35, color: "99, 102, 241", speed: 0.0003, phase: 0 },
      { x: 0.8, y: 0.1, r: 0.25, color: "168, 85, 247", speed: 0.0004, phase: 1.5 },
      { x: 0.2, y: 0.7, r: 0.3, color: "245, 158, 11", speed: 0.00025, phase: 3 },
      { x: 0.7, y: 0.6, r: 0.2, color: "34, 197, 94", speed: 0.00035, phase: 4.5 },
    ];

    function draw() {
      if (!ctx || !canvas) return;
      time += 1;
      ctx.clearRect(0, 0, canvas.width, canvas.height);

      for (const blob of blobs) {
        const cx =
          canvas.width *
          (blob.x + Math.sin(time * blob.speed + blob.phase) * 0.1);
        const cy =
          canvas.height *
          (blob.y + Math.cos(time * blob.speed * 0.7 + blob.phase) * 0.08);
        const radius = Math.min(canvas.width, canvas.height) * blob.r;

        const gradient = ctx.createRadialGradient(cx, cy, 0, cx, cy, radius);
        gradient.addColorStop(0, `rgba(${blob.color}, 0.12)`);
        gradient.addColorStop(0.5, `rgba(${blob.color}, 0.04)`);
        gradient.addColorStop(1, `rgba(${blob.color}, 0)`);

        ctx.fillStyle = gradient;
        ctx.fillRect(0, 0, canvas.width, canvas.height);
      }

      animationId = requestAnimationFrame(draw);
    }

    draw();

    return () => {
      window.removeEventListener("resize", resize);
      cancelAnimationFrame(animationId);
    };
  }, []);

  return (
    <canvas
      ref={canvasRef}
      className="pointer-events-none fixed inset-0 z-0"
      style={{ opacity: 0.8 }}
    />
  );
}
