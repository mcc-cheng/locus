import { useEffect, useRef } from "react";
import embed, { type Result } from "vega-embed";

/**
 * Renders a Vega-Lite spec. Exposes the embed Result via `onView` so callers can
 * export PNG/SVG.
 */
export function VegaChart({
  spec,
  onView,
}: {
  spec: Record<string, unknown>;
  onView?: (result: Result) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let result: Result | undefined;
    let cancelled = false;
    if (ref.current) {
      embed(ref.current, spec as never, { actions: false, renderer: "canvas" })
        .then((r) => {
          if (cancelled) {
            r.finalize();
            return;
          }
          result = r;
          onView?.(r);
        })
        .catch(() => {
          /* spec render errors are surfaced by the caller's data state */
        });
    }
    return () => {
      cancelled = true;
      result?.finalize();
    };
  }, [spec, onView]);

  return <div ref={ref} className="overflow-x-auto" />;
}
