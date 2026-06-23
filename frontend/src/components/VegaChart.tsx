import { useEffect, useRef, useState } from "react";
import { compile } from "vega-lite";
import { View, parse } from "vega";

/**
 * Renders a Vega-Lite spec by compiling it and drawing it with Vega's SVG
 * renderer into a self-contained SVG. We deliberately do NOT use vega-embed:
 * its canvas + "container" autosizing renders 0-wide inside flex layouts, which
 * is what made charts disappear. An SVG with an explicit width always displays.
 *
 * Exposes the live Vega ``View`` via ``onView`` so callers can export PNG/SVG
 * (``view.toImageURL`` / ``view.toSVG``).
 */
export interface ChartView {
  toImageURL(type: string, scale?: number): Promise<string>;
  toSVG(): Promise<string>;
}

const _LAYOUT_KEYS = ["facet", "repeat", "concat", "hconcat", "vconcat"];

export function VegaChart({
  spec,
  onView,
}: {
  spec: Record<string, unknown>;
  onView?: (view: ChartView) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    let view: View | undefined;
    let cancelled = false;
    setError(null);

    try {
      // Top-level width only applies to single-view / layered specs; give the
      // chart the container's measured pixel width so it fits and is visible.
      const sizable = !_LAYOUT_KEYS.some((k) => k in spec);
      const width = Math.max(240, Math.floor(el.clientWidth || el.offsetWidth || 360) - 4);
      const sized = sizable ? { ...spec, width } : spec;
      const vega = compile(sized as never).spec;
      view = new View(parse(vega), { renderer: "svg" });
      view.initialize(el);
      view
        .runAsync()
        .then(() => {
          if (!cancelled && view) onView?.(view as unknown as ChartView);
        })
        .catch((e) => {
          if (!cancelled) setError(String(e?.message ?? e));
        });
    } catch (e) {
      setError(String((e as Error)?.message ?? e));
    }

    return () => {
      cancelled = true;
      view?.finalize();
    };
  }, [spec, onView]);

  return (
    <div>
      <div ref={ref} className="overflow-x-auto" />
      {error && <p className="mt-1 text-xs text-red-500">Couldn't render this chart: {error}</p>}
    </div>
  );
}
