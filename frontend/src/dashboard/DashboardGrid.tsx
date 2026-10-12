import {
  DndContext,
  DragOverlay,
  PointerSensor,
  useSensor,
  useSensors,
  type DragMoveEvent,
  type DragStartEvent,
} from "@dnd-kit/core";
import { useReducedMotion } from "framer-motion";
import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { createPortal, flushSync } from "react-dom";
import { BoardWidget, REFLOW_SECONDS, WidgetCard } from "./WidgetShell";
import {
  colOf,
  isFull,
  layoutBoard,
  nudge,
  pickPlacement,
  shorterColumn,
  type BoardMetrics,
  type Col,
  type Direction,
} from "./layout";
import { widgetIds } from "./order";
import { TITLES } from "./widgetMeta";
import { NARROW_SCREEN, useMediaQuery } from "@/lib/useMediaQuery";
import type { Widget } from "@/lib/types";

const DROP = { duration: REFLOW_SECONDS * 1000, easing: "cubic-bezier(0.2, 0, 0, 1)" };
const FALLBACK_GAP = 24;
// At most this many layout corrections in this many milliseconds (see `read`).
const BURST_LIMIT = 12;
const BURST_MS = 250;
const MOVED: Record<Direction, string> = {
  up: "moved up",
  down: "moved down",
  left: "moved to the left column",
  right: "moved to the right column",
};

interface Measured {
  heights: Record<string, number>;
  gap: number;
}

function sameMeasure(a: Measured, heights: Record<string, number>, gap: number): boolean {
  const keys = Object.keys(heights);
  return (
    a.gap === gap &&
    keys.length === Object.keys(a.heights).length &&
    keys.every((k) => a.heights[k] === heights[k])
  );
}

export interface DashboardGridHandle {
  /** The column with more room: where a newly added widget should go. */
  shorterColumn: () => Col;
}

/**
 * The board. Widgets pack into two columns (one on a narrow screen) with no
 * holes; their positions come from `layoutBoard`, fed by each widget's measured
 * height. Dragging moves a widget to whichever free place is nearest its card.
 */
export const DashboardGrid = forwardRef<
  DashboardGridHandle,
  {
    widgets: Widget[];
    editing: boolean;
    onReorder: (widgets: Widget[]) => void;
    onToggleExpand: (i: number) => void;
    onRemove: (i: number) => void;
  }
>(function DashboardGrid({ widgets, editing, onReorder, onToggleExpand, onRemove }, ref) {
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 4 } }));
  const columns = useMediaQuery(NARROW_SCREEN) ? 1 : 2;
  const reduceMotion = useReducedMotion();

  const gridRef = useRef<HTMLDivElement>(null);
  const [measured, setMeasured] = useState<Measured>({ heights: {}, gap: FALLBACK_GAP });
  // During a drag the arrangement lives here; it is saved once, on drop.
  const [draft, setDraft] = useState<Widget[] | null>(null);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [announcement, setAnnouncement] = useState("");
  const dragOrigin = useRef({ x: 0, y: 0 }); // the card's top-left when picked up
  const refocus = useRef<string | null>(null);
  const settled = useRef(false); // the first measured layout has been painted
  const instant = useRef(false); // the current re-render follows a resize
  const sent = useRef<Measured>({ heights: {}, gap: FALLBACK_GAP }); // last reading given to React
  const burst = useRef({ since: 0, count: 0 });

  const items = draft ?? widgets;
  const ids = useMemo(() => widgetIds(items), [items]);
  const metrics = useMemo<BoardMetrics>(() => ({ ...measured, columns }), [measured, columns]);
  const { tops, height } = layoutBoard(items, ids, metrics);
  const active = activeId ? items[ids.indexOf(activeId)] : undefined;
  const reflow = settled.current && !instant.current && !reduceMotion ? REFLOW_SECONDS : 0;

  // Read the widgets' heights from the page. Returns a reading only when it
  // differs from the last one handed to React, so re-measuring an unchanged board
  // never schedules a render. The reading is set as a plain value, not built in
  // a `setState(prev => ...)` updater: React can replay queued updaters on later
  // renders, and one that returns a new object each time gives the state a new
  // identity on every render, which re-triggers this measurement without end.
  const read = useCallback((): Measured | null => {
    const grid = gridRef.current;
    if (!grid) return null;
    const heights: Record<string, number> = {};
    for (const el of Array.from(grid.children) as HTMLElement[]) {
      if (el.dataset.widget) heights[el.dataset.widget] = el.offsetHeight;
    }
    const gap = parseFloat(getComputedStyle(grid).columnGap) || FALLBACK_GAP;
    if (sameMeasure(sent.current, heights, gap)) return null;
    // Backstop: positions depend on heights, and a height could in principle
    // depend on positions (a scrollbar appearing narrows the page). Rather than
    // chase such a cycle, stop after a burst and keep the layout we have.
    const now = performance.now();
    if (now - burst.current.since > BURST_MS) burst.current = { since: now, count: 0 };
    if (++burst.current.count > BURST_LIMIT) return null;
    sent.current = { heights, gap };
    return sent.current;
  }, []);

  // After every render and before the browser paints, so a widget that was just
  // added or expanded is in the right place from its first frame.
  useLayoutEffect(() => {
    const next = read();
    if (next) setMeasured(next);
  });

  // Heights that change without this component rendering (data arriving, the
  // window or sidebar resizing) arrive here. A resize is followed, not animated.
  const watched = useMemo(() => [...ids].sort().join("|"), [ids]);
  useEffect(() => {
    const grid = gridRef.current;
    if (!grid) return;
    let width = grid.clientWidth;
    const observer = new ResizeObserver(() => {
      const resized = grid.clientWidth !== width;
      width = grid.clientWidth;
      const next = read();
      if (!next) return;
      instant.current = resized;
      flushSync(() => setMeasured(next)); // before this frame paints, so nothing overlaps
      instant.current = false;
    });
    observer.observe(grid);
    for (const el of Array.from(grid.children)) observer.observe(el);
    return () => observer.disconnect();
  }, [read, watched]);

  useEffect(() => {
    if (Object.keys(measured.heights).length > 0) settled.current = true;
  }, [measured]);

  useImperativeHandle(
    ref,
    () => ({ shorterColumn: () => shorterColumn(widgets, widgetIds(widgets), metrics) }),
    [widgets, metrics],
  );

  const onDragStart = (e: DragStartEvent) => {
    const id = String(e.active.id);
    const index = ids.indexOf(id);
    const grid = gridRef.current;
    if (index < 0 || !grid) return;
    const right = !isFull(items[index], columns) && colOf(items[index]) === 1;
    dragOrigin.current = {
      x: right ? (grid.clientWidth + metrics.gap) / 2 : 0,
      y: tops[id] ?? 0,
    };
    setActiveId(id);
    setDraft(widgets);
  };

  const onDragMove = (e: DragMoveEvent) => {
    const grid = gridRef.current;
    const index = activeId ? ids.indexOf(activeId) : -1;
    if (!grid || index < 0) return;
    // `delta` already accounts for any scrolling since the drag began.
    const card = { x: dragOrigin.current.x + e.delta.x, y: dragOrigin.current.y + e.delta.y };
    const next = pickPlacement(items, ids, index, card, metrics, grid.clientWidth);
    if (next) setDraft(next.widgets);
  };

  const finish = (commit: boolean) => {
    if (commit && draft && draft.some((w, i) => w !== widgets[i])) onReorder(draft);
    setDraft(null);
    setActiveId(null);
  };

  const onNudge = (index: number, direction: Direction) => {
    const next = nudge(widgets, index, direction, columns);
    if (next === widgets) return;
    refocus.current = ids[index];
    setAnnouncement(`${TITLES[widgets[index].type]} ${MOVED[direction]}.`);
    onReorder(next);
  };

  // Moving a card in the page can drop keyboard focus; put it back on the grip.
  useEffect(() => {
    if (!refocus.current) return;
    document.querySelector<HTMLElement>(`[data-grip="${refocus.current}"]`)?.focus();
    refocus.current = null;
  }, [widgets]);

  return (
    <DndContext
      sensors={sensors}
      onDragStart={onDragStart}
      onDragMove={onDragMove}
      onDragEnd={() => finish(true)}
      onDragCancel={() => finish(false)}
      accessibility={{
        announcements: {
          onDragStart: ({ active: a }) => `Picked up ${titleOf(a.id)}.`,
          onDragOver: () => undefined,
          onDragEnd: ({ active: a }) => `${titleOf(a.id)} dropped.`,
          onDragCancel: ({ active: a }) => `Moving ${titleOf(a.id)} cancelled.`,
        },
      }}
    >
      <div
        ref={gridRef}
        className={`dashgrid dashgrid--${columns === 1 ? "one" : "two"}${activeId ? " dashgrid--dragging" : ""}`}
        style={{ height }}
      >
        {items.map((w, i) => (
          <BoardWidget
            key={ids[i]}
            id={ids[i]}
            widget={w}
            index={i}
            top={tops[ids[i]] ?? 0}
            place={isFull(w, columns) ? "full" : colOf(w) === 0 ? "left" : "right"}
            reflow={reflow}
            editing={editing}
            onToggleExpand={onToggleExpand}
            onRemove={onRemove}
            onNudge={onNudge}
          />
        ))}
      </div>
      {createPortal(
        <DragOverlay dropAnimation={DROP}>
          {active ? (
            <div className="widget widget--overlay card">
              <WidgetCard widget={active} editing preview />
            </div>
          ) : null}
        </DragOverlay>,
        document.body,
      )}
      <div className="sr-only" aria-live="polite">
        {announcement}
      </div>
    </DndContext>
  );
});

function titleOf(id: string | number): string {
  const type = String(id).replace(/-\d+$/, "") as keyof typeof TITLES;
  return TITLES[type] ?? "widget";
}
