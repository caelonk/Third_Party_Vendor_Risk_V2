import {
  DndContext,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import { SortableContext, arrayMove, rectSortingStrategy } from "@dnd-kit/sortable";
import { WidgetShell } from "./WidgetShell";
import type { Widget } from "@/lib/types";

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
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 6 } }));
  const ids = widgets.map((w, i) => `${w.type}-${i}`);

  const onDragEnd = (e: DragEndEvent) => {
    const { active, over } = e;
    if (!over || active.id === over.id) return;
    const from = ids.indexOf(String(active.id));
    const to = ids.indexOf(String(over.id));
    if (from < 0 || to < 0) return;
    onReorder(arrayMove(widgets, from, to));
  };

  return (
    <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}>
      <SortableContext items={ids} strategy={rectSortingStrategy}>
        <div className="dashgrid">
          {widgets.map((w, i) => (
            <WidgetShell
              key={ids[i]}
              widget={w}
              index={i}
              editing={editing}
              onToggleExpand={onToggleExpand}
              onRemove={onRemove}
            />
          ))}
        </div>
      </SortableContext>
    </DndContext>
  );
}
