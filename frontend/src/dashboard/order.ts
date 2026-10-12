import type { Widget } from "@/lib/types";

/**
 * Stable ids for the board's widgets. A widget keeps its id when it moves, so
 * React moves the existing card instead of rebuilding it and the reflow can be
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

export interface Box {
  top: number;
  left: number;
  width: number;
  height: number;
}

/**
 * Whether the dragged widget should take the place of the one under the pointer.
 *
 * It does once the pointer is past the middle of that widget, on the side away
 * from where the dragged widget's slot currently is. Widgets differ in size, so
 * "whatever is under the pointer" alone would swap two widgets back and forth as
 * the grid reflows; after a swap made by this rule the pointer is still on the
 * far side of the middle, so it settles.
 */
export function shouldTakePlace(slot: Box, target: Box, pointer: { x: number; y: number }): boolean {
  const sameRow = Math.abs(target.top - slot.top) < 2;
  if (sameRow) {
    const middle = target.left + target.width / 2;
    return target.left > slot.left ? pointer.x > middle : pointer.x < middle;
  }
  const middle = target.top + target.height / 2;
  return target.top > slot.top ? pointer.y > middle : pointer.y < middle;
}

/** Move one item by `step` places (clamped). Returns the same array if it can't move. */
export function moveBy<T>(items: T[], index: number, step: number): T[] {
  const to = Math.max(0, Math.min(items.length - 1, index + step));
  if (to === index || index < 0 || index >= items.length) return items;
  const next = items.slice();
  const [item] = next.splice(index, 1);
  next.splice(to, 0, item);
  return next;
}
