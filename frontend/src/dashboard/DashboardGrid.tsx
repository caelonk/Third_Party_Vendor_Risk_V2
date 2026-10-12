import {
  DndContext,
  DragOverlay,
  PointerSensor,
  pointerWithin,
  useSensor,
  useSensors,
  type CollisionDetection,
  type DragOverEvent,
  type DragStartEvent,
} from "@dnd-kit/core";
import { SortableContext, arrayMove } from "@dnd-kit/sortable";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { REFLOW_SECONDS, SortableWidget, WidgetCard } from "./WidgetShell";
import { moveBy, shouldTakePlace, widgetIds } from "./order";
import { TITLES } from "./widgetMeta";
import type { Widget } from "@/lib/types";

// The grid is reordered for real while dragging and each card animates to its
// new place, so dnd-kit's own "shift the neighbours" transforms are not used.
const noShift = () => null;
const DROP = { duration: REFLOW_SECONDS * 1000, easing: "cubic-bezier(0.2, 0, 0, 1)" };

export function DashboardGrid({
  widgets,
  editing,
  onReorder,
  onToggleExpand,
  onRemove,
}: {
  widgets: Widget[];
  editing: boolean;
  onReorder: (widgets: Widget[]) => void;
  onToggleExpand: (i: number) => void;
  onRemove: (i: number) => void;
}) {
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 4 } }));

  // During a drag the order lives here; it is saved once, on drop.
  const [draft, setDraft] = useState<Widget[] | null>(null);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [announcement, setAnnouncement] = useState("");
  const settleUntil = useRef(0);
  const refocus = useRef<string | null>(null);

  const items = draft ?? widgets;
  const ids = useMemo(() => widgetIds(items), [items]);
  const active = activeId ? items[ids.indexOf(activeId)] : undefined;

  // Which widget, if any, the dragged one should change places with right now.
  const collisionDetection = useCallback<CollisionDetection>((args) => {
    const { active: dragged, pointerCoordinates, droppableRects } = args;
    if (!pointerCoordinates || performance.now() < settleUntil.current) return [];
    const hit = pointerWithin(args).find((c) => c.id !== dragged.id);
    const slot = droppableRects.get(dragged.id);
    const target = hit && droppableRects.get(hit.id);
    return hit && slot && target && shouldTakePlace(slot, target, pointerCoordinates) ? [hit] : [];
  }, []);

  const onDragStart = (e: DragStartEvent) => {
    setActiveId(String(e.active.id));
    setDraft(widgets);
  };

  const onDragOver = ({ active: dragged, over }: DragOverEvent) => {
    if (!over || over.id === dragged.id) return;
    const from = ids.indexOf(String(dragged.id));
    const to = ids.indexOf(String(over.id));
    if (from < 0 || to < 0) return;
    // Let the cards finish sliding before the next change of places.
    settleUntil.current = performance.now() + REFLOW_SECONDS * 1000;
    setDraft(arrayMove(items, from, to));
  };

  const finish = (commit: boolean) => {
    if (commit && draft && draft.some((w, i) => w !== widgets[i])) onReorder(draft);
    setDraft(null);
    setActiveId(null);
  };

  const onNudge = (index: number, step: -1 | 1) => {
    const next = moveBy(widgets, index, step);
    if (next === widgets) return;
    const title = TITLES[widgets[index].type];
    refocus.current = ids[index];
    setAnnouncement(`${title} moved to position ${next.indexOf(widgets[index]) + 1} of ${next.length}.`);
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
      collisionDetection={collisionDetection}
      onDragStart={onDragStart}
      onDragOver={onDragOver}
      onDragEnd={() => finish(true)}
      onDragCancel={() => finish(false)}
      accessibility={{
        announcements: {
          onDragStart: ({ active: a }) => `Picked up ${titleOf(a.id)}.`,
          onDragOver: ({ active: a, over }) =>
            over
              ? `${titleOf(a.id)} moved to position ${ids.indexOf(String(over.id)) + 1} of ${ids.length}.`
              : undefined,
          onDragEnd: ({ active: a }) => `${titleOf(a.id)} dropped.`,
          onDragCancel: ({ active: a }) => `Reordering ${titleOf(a.id)} cancelled.`,
        },
      }}
    >
      <SortableContext items={ids} strategy={noShift}>
        <div className={`dashgrid${activeId ? " dashgrid--dragging" : ""}`}>
          {items.map((w, i) => (
            <SortableWidget
              key={ids[i]}
              id={ids[i]}
              widget={w}
              index={i}
              editing={editing}
              onToggleExpand={onToggleExpand}
              onRemove={onRemove}
              onNudge={onNudge}
            />
          ))}
        </div>
      </SortableContext>
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
}

function titleOf(id: string | number): string {
  const type = String(id).replace(/-\d+$/, "") as keyof typeof TITLES;
  return TITLES[type] ?? "widget";
}
