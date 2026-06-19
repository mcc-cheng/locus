import { useId } from "react";

/**
 * The Locus mark: a 4×4 data grid where the active violet dots trace an "L"
 * (left column + bottom row) with a glow on the corner. Recreated as crisp
 * vector from the original concept, with a violet gradient and soft glow.
 */
const CENTERS = [12, 24, 36, 48];
const isActive = (cx: number, cy: number) => cx === 12 || cy === 48; // the "L"
const isCorner = (cx: number, cy: number) => cx === 12 && cy === 48;

export function LocusLogo({ className = "h-8 w-8" }: { className?: string }) {
  const uid = useId().replace(/:/g, "");
  const grad = `locus-grad-${uid}`;
  const glow = `locus-glow-${uid}`;
  return (
    <svg
      viewBox="0 0 60 60"
      className={className}
      role="img"
      aria-label="Locus"
      xmlns="http://www.w3.org/2000/svg"
    >
      <defs>
        <linearGradient id={grad} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#c4b1ff" />
          <stop offset="100%" stopColor="#7c3aed" />
        </linearGradient>
        <filter id={glow} x="-60%" y="-60%" width="220%" height="220%">
          <feGaussianBlur stdDeviation="2.6" />
        </filter>
      </defs>
      <rect width="60" height="60" rx="14" fill="#0f0f1e" />
      {/* soft glow behind the corner dot */}
      <circle cx="12" cy="48" r="7.5" fill="#8b5cf6" opacity="0.5" filter={`url(#${glow})`} />
      {CENTERS.map((cy) =>
        CENTERS.map((cx) => {
          const active = isActive(cx, cy);
          return (
            <circle
              key={`${cx}-${cy}`}
              cx={cx}
              cy={cy}
              r={isCorner(cx, cy) ? 5 : 4}
              fill={active ? `url(#${grad})` : "#363651"}
            />
          );
        }),
      )}
    </svg>
  );
}
