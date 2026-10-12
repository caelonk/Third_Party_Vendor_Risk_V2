import type { Widget } from "@/lib/types";

/**
 * Stable ids for the board's widgets. A widget keeps its id when it moves, so
 * React moves the existing card instead of rebuilding it and the move can be
 * animated. Each type appears once on a board; a repeat (from an old saved
 * layout) gets a numbered suffix.
 */
export function widgetIds(widgets: Widget[]): string[] {
  const seen = new Map<string, number>();
  return widgets.map((w) => {
    const n = seen.get(w.type) ?? 0;
    seen.set(w.type, n + 1);
    return n === 0 ? w.type : `${w.type}-${n}`;
  });
}
