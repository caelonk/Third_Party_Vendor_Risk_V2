import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { motion } from "framer-motion";
import { GripVertical, Maximize2, Minimize2, X } from "lucide-react";
import type { CSSProperties } from "react";
import { WIDGET_COMPONENTS } from "./widgets";
import { TITLES } from "./widgetMeta";
import type { Widget } from "@/lib/types";

export function WidgetShell({
  widget,
  index,
  editing,
  onToggleExpand,
  onRemove,
}: {
  widget: Widget;
  index: number;
  editing: boolean;
  onToggleExpand: (i: number) => void;
  onRemove: (i: number) => void;
}) {
  const id = `${widget.type}-${index}`;
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id,
    disabled: !editing,
  });
  const Content = WIDGET_COMPONENTS[widget.type];

  const style: CSSProperties = {
    transform: CSS.Transform.toString(transform),
    transition,
    gridColumn: widget.expanded ? "span 2" : "span 1",
    zIndex: isDragging ? 5 : undefined,
    opacity: isDragging ? 0.85 : 1,
  };

  return (
    <motion.div layout ref={setNodeRef} style={style} className="widget card">
      <div className="widget__header">
        {editing && (
          <button className="widget__grip" {...attributes} {...listeners} aria-label="Drag to reorder">
            <GripVertical size={15} />
          </button>
        )}
        <span className="widget__title">{TITLES[widget.type]}</span>
        <div className="widget__actions">
          <button
            className="icon-btn"
            onClick={() => onToggleExpand(index)}
            title={widget.expanded ? "Minimize" : "Expand"}
          >
            {widget.expanded ? <Minimize2 size={15} /> : <Maximize2 size={15} />}
          </button>
          {editing && (
            <button className="icon-btn" onClick={() => onRemove(index)} title="Remove">
              <X size={15} />
            </button>
          )}
        </div>
      </div>
      <div className="widget__body">
        <Content expanded={widget.expanded} />
      </div>
    </motion.div>
  );
}
