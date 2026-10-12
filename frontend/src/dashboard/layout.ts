import type { Widget } from "@/lib/types";

/**
 * Where the board's widgets sit.
 *
 * The board is two columns that pack independently: each widget sits directly
 * under the one above it in its own column, so a short widget never leaves a
 * hole beside a tall one. An expanded widget spans both columns and starts below
 * whatever is above it in either. On a narrow screen there is one column and
 * every widget is full width.
 *
 * The saved layout is an ordered list; each widget also records its column
 * (`col`). Order decides top-to-bottom within a column, and the reading order on
 * a narrow screen.
 */
export type Col = 0 | 1;

export interface BoardMetrics {
  /** Measured height of each widget, by id, in px. */
  heights: Record<string, number>;
  /** Space between neighbouring widgets, in px (both directions). */
  gap: number;
  columns: 1 | 2;
}

export interface Rect {
  left: number;
  top: number;
  width: number;
  height: number;
}

export function colOf(w: Widget): Col {
  return w.col === 1 ? 1 : 0;
}

/** Whether a widget takes the whole width of the board. */
export function isFull(w: Widget, columns: 1 | 2): boolean {
  return columns === 1 || w.expanded;
}

/**
 * Give every widget a column. Layouts saved before columns existed flowed left
 * to right, two per row, restarting after each expanded widget; this keeps each
 * widget on the side it was on.
 */
export function withColumns(widgets: Widget[]): Widget[] {
  let run = 0;
  return widgets.map((w) => {
    if (w.expanded) {
      run = 0;
      return w;
    }
    const flowed: Col = run % 2 === 0 ? 0 : 1;
    run += 1;
    return w.col === 0 || w.col === 1 ? w : { ...w, col: flowed };
  });
}

/** The top of each widget (px from the top of the board), and the board's height. */
export function layoutBoard(
  widgets: Widget[],
  ids: string[],
  { heights, gap, columns }: BoardMetrics,
): { tops: Record<string, number>; height: number } {
  const bottoms = [0, 0]; // where the next widget in each column would start
  const tops: Record<string, number> = {};
  widgets.forEach((w, i) => {
    const height = heights[ids[i]] ?? 0;
    if (isFull(w, columns)) {
      const top = Math.max(bottoms[0], bottoms[1]);
      tops[ids[i]] = top;
      bottoms[0] = bottoms[1] = top + height + gap;
    } else {
      const col = colOf(w);
      tops[ids[i]] = bottoms[col];
      bottoms[col] += height + gap;
    }
  });
  const end = Math.max(bottoms[0], bottoms[1]);
  return { tops, height: end > 0 ? end - gap : 0 };
}

/** The column whose content currently ends higher up: where a new widget fits best. */
export function shorterColumn(widgets: Widget[], ids: string[], metrics: BoardMetrics): Col {
  const bottoms = [0, 0];
  widgets.forEach((w, i) => {
    const height = (metrics.heights[ids[i]] ?? 0) + metrics.gap;
    if (w.expanded) bottoms[0] = bottoms[1] = Math.max(bottoms[0], bottoms[1]) + height;
    else bottoms[colOf(w)] += height;
  });
  return bottoms[1] < bottoms[0] ? 1 : 0;
}

function slotRect(
  widgets: Widget[],
  ids: string[],
  index: number,
  metrics: BoardMetrics,
  width: number,
): Rect {
  const w = widgets[index];
  const { tops } = layoutBoard(widgets, ids, metrics);
  const full = isFull(w, metrics.columns);
  const colWidth = (width - metrics.gap) / 2;
  return {
    left: full || colOf(w) === 0 ? 0 : colWidth + metrics.gap,
    top: tops[ids[index]],
    width: full ? width : colWidth,
    height: metrics.heights[ids[index]] ?? 0,
  };
}

/** A dragged card must be this much closer (px) to another place before it moves there. */
export const STICKINESS = 12;

/**
 * Where a dragged widget should go, given where its card currently is.
 *
 * Every place it could occupy is tried (each position in the list, in either
 * column), the board is laid out for each, and the place whose slot ends up
 * nearest the card wins. Because the candidates do not depend on where the slot
 * is now, the answer is a function of the card's position alone: it cannot
 * flip-flop as the other widgets reflow. `STICKINESS` keeps it from switching
 * back and forth when the card is held between two places.
 *
 * @param point the card's top-left corner, in board coordinates
 * @returns the rearranged list and its ids, or null if the widget should stay put
 */
export function pickPlacement(
  widgets: Widget[],
  ids: string[],
  index: number,
  point: { x: number; y: number },
  metrics: BoardMetrics,
  width: number,
): { widgets: Widget[]; ids: string[] } | null {
  const distance = (r: Rect) => Math.hypot(r.left - point.x, r.top - point.y);
  const active = widgets[index];
  const activeId = ids[index];
  const rest = widgets.filter((_, i) => i !== index);
  const restIds = ids.filter((_, i) => i !== index);

  const current = distance(slotRect(widgets, ids, index, metrics, width));
  let best: { widgets: Widget[]; ids: string[] } | null = null;
  let bestDistance = current;

  const columns: Col[] = isFull(active, metrics.columns) ? [colOf(active)] : [0, 1];
  for (const col of columns) {
    const moved = colOf(active) === col && active.col !== undefined ? active : { ...active, col };
    for (let at = 0; at <= rest.length; at++) {
      const candidate = [...rest.slice(0, at), moved, ...rest.slice(at)];
      const candidateIds = [...restIds.slice(0, at), activeId, ...restIds.slice(at)];
      const d = distance(slotRect(candidate, candidateIds, at, metrics, width));
      if (d < bestDistance - 0.5) {
        best = { widgets: candidate, ids: candidateIds };
        bestDistance = d;
      }
    }
  }
  return best && bestDistance < current - STICKINESS ? best : null;
}

export type Direction = "up" | "down" | "left" | "right";

/** Two widgets stack in the same vertical run if they share a column or either is full width. */
function stacked(a: Widget, b: Widget, columns: 1 | 2): boolean {
  return columns === 1 || a.expanded || b.expanded || colOf(a) === colOf(b);
}

/**
 * Keyboard reordering. Up and down move a widget past its neighbour in the same
 * column; left and right move it to the other column. Returns the same array if
 * the widget cannot move that way.
 */
export function nudge(
  widgets: Widget[],
  index: number,
  direction: Direction,
  columns: 1 | 2,
): Widget[] {
  const w = widgets[index];
  if (!w) return widgets;

  if (direction === "left" || direction === "right") {
    const col: Col = direction === "left" ? 0 : 1;
    if (isFull(w, columns) || colOf(w) === col) return widgets;
    return widgets.map((other, i) => (i === index ? { ...w, col } : other));
  }

  const step = direction === "up" ? -1 : 1;
  let to = index + step;
  while (to >= 0 && to < widgets.length && !stacked(w, widgets[to], columns)) to += step;
  if (to < 0 || to >= widgets.length) return widgets;
  const next = widgets.slice();
  next.splice(index, 1);
  next.splice(to, 0, w);
  return next;
}
