import { useSortable } from "@dnd-kit/sortable";
import { motion } from "framer-motion";
import { GripVertical, Maximize2, Minimize2, X } from "lucide-react";
import type { HTMLAttributes, KeyboardEvent } from "react";
import { WIDGET_COMPONENTS } from "./widgets";
import { TITLES } from "./widgetMeta";
import type { Widget } from "@/lib/types";

/** How long the other widgets take to slide to their new places. */
export const REFLOW_SECONDS = 0.22;
const REFLOW_EASE = [0.2, 0, 0, 1] as const;

/** The card itself: header (grip, title, actions) and the widget's content. */
export function WidgetCard({
  widget,
  editing,
  preview = false,
  gripRef,
  gripProps,
  onToggleExpand,
  onRemove,
}: {
  widget: Widget;
  editing: boolean;
  /** The copy that follows the pointer during a drag: static, not interactive. */
  preview?: boolean;
  gripRef?: (el: HTMLButtonElement | null) => void;
  gripProps?: HTMLAttributes<HTMLButtonElement> & { "data-grip"?: string };
  onToggleExpand?: () => void;
  onRemove?: () => void;
}) {
  const Content = WIDGET_COMPONENTS[widget.type];
  return (
    <>
      <div className="widget__header">
        {editing && (
          <button type="button" className="widget__grip" ref={gripRef} {...gripProps}>
            <GripVertical size={15} />
          </button>
        )}
        <span className="widget__title">{TITLES[widget.type]}</span>
        <div className="widget__actions">
          <button
            type="button"
            className="icon-btn"
            onClick={onToggleExpand}
            title={widget.expanded ? "Minimize" : "Expand"}
            tabIndex={preview ? -1 : undefined}
          >
            {widget.expanded ? <Minimize2 size={15} /> : <Maximize2 size={15} />}
          </button>
          {editing && (
            <button
              type="button"
              className="icon-btn"
              onClick={onRemove}
              title="Remove"
              tabIndex={preview ? -1 : undefined}
            >
              <X size={15} />
            </button>
          )}
        </div>
      </div>
      <div className="widget__body">
        <Content expanded={widget.expanded} preview={preview} />
      </div>
    </>
  );
}

/**
 * A widget in the grid. While it is being dragged this is the empty slot that
 * marks where it will land; the visible card is the copy in the drag overlay.
 * The grid itself is reordered as the pointer moves, and `layout` animates each
 * card from its old place to its new one.
 */
export function SortableWidget({
  id,
  widget,
  index,
  editing,
  onToggleExpand,
  onRemove,
  onNudge,
}: {
  id: string;
  widget: Widget;
  index: number;
  editing: boolean;
  onToggleExpand: (i: number) => void;
  onRemove: (i: number) => void;
  /** Keyboard reordering: move this widget one place earlier (-1) or later (+1). */
  onNudge: (i: number, step: -1 | 1) => void;
}) {
  const { listeners, setNodeRef, setActivatorNodeRef, isDragging } = useSortable({
    id,
    disabled: !editing,
  });

  const onKeyDown = (e: KeyboardEvent<HTMLButtonElement>) => {
    const step =
      e.key === "ArrowUp" || e.key === "ArrowLeft"
        ? -1
        : e.key === "ArrowDown" || e.key === "ArrowRight"
          ? 1
          : 0;
    if (!step) return;
    e.preventDefault();
    onNudge(index, step);
  };

  return (
    <motion.div
      layout="position"
      transition={{ layout: { duration: REFLOW_SECONDS, ease: REFLOW_EASE } }}
      ref={setNodeRef}
      style={{ gridColumn: widget.expanded ? "span 2" : "span 1" }}
      className={`widget card${isDragging ? " widget--slot" : ""}`}
    >
      <WidgetCard
        widget={widget}
        editing={editing}
        gripRef={setActivatorNodeRef}
        gripProps={{
          ...listeners,
          onKeyDown,
          "aria-label": `Reorder ${TITLES[widget.type]}. Drag, or use the arrow keys.`,
          "data-grip": id,
        }}
        onToggleExpand={() => onToggleExpand(index)}
        onRemove={() => onRemove(index)}
      />
    </motion.div>
  );
}
