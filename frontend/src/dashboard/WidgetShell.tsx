import { useDraggable } from "@dnd-kit/core";
import { motion } from "framer-motion";
import { GripVertical, Maximize2, Minimize2, X } from "lucide-react";
import type { HTMLAttributes, KeyboardEvent } from "react";
import { WIDGET_COMPONENTS } from "./widgets";
import { TITLES } from "./widgetMeta";
import type { Direction } from "./layout";
import type { Widget } from "@/lib/types";

/** How long the other widgets take to slide to their new places. */
export const REFLOW_SECONDS = 0.22;
const REFLOW_EASE = [0.2, 0, 0, 1] as const;

const ARROWS: Record<string, Direction> = {
  ArrowUp: "up",
  ArrowDown: "down",
  ArrowLeft: "left",
  ArrowRight: "right",
};

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
 * A widget on the board, placed at `top` in its column (see dashboard/layout).
 * While it is being dragged this is the empty slot marking where it will land;
 * the visible card is the copy in the drag overlay. Whenever its place changes,
 * `layout` slides it from the old place to the new one.
 */
export function BoardWidget({
  id,
  widget,
  index,
  top,
  place,
  reflow,
  editing,
  onToggleExpand,
  onRemove,
  onNudge,
}: {
  id: string;
  widget: Widget;
  index: number;
  top: number;
  place: "full" | "left" | "right";
  /** Seconds a move takes; 0 places it at once (first layout, window resize). */
  reflow: number;
  editing: boolean;
  onToggleExpand: (i: number) => void;
  onRemove: (i: number) => void;
  /** Keyboard reordering: up/down within its column, left/right to the other one. */
  onNudge: (i: number, direction: Direction) => void;
}) {
  const { listeners, setNodeRef, setActivatorNodeRef, isDragging } = useDraggable({
    id,
    disabled: !editing,
  });

  const onKeyDown = (e: KeyboardEvent<HTMLButtonElement>) => {
    const direction = ARROWS[e.key];
    if (!direction) return;
    e.preventDefault();
    onNudge(index, direction);
  };

  return (
    <motion.div
      layout="position"
      transition={{ layout: { duration: reflow, ease: REFLOW_EASE } }}
      ref={setNodeRef}
      data-widget={id}
      style={{ top }}
      className={`widget widget--${place} card${isDragging ? " widget--slot" : ""}`}
    >
      <WidgetCard
        widget={widget}
        editing={editing}
        gripRef={setActivatorNodeRef}
        gripProps={{
          ...listeners,
          onKeyDown,
          "aria-label": `Move ${TITLES[widget.type]}. Drag it, or use the arrow keys.`,
          "data-grip": id,
        }}
        onToggleExpand={() => onToggleExpand(index)}
        onRemove={() => onRemove(index)}
      />
    </motion.div>
  );
}
