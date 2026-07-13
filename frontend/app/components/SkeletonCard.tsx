"use client";

export default function SkeletonCard({
  height = "14rem",
  className = "",
}: {
  height?: string;
  className?: string;
}) {
  return (
    <div
      className={`glass-card skeleton-shimmer ${className}`}
      style={{ height, minHeight: height }}
    />
  );
}
