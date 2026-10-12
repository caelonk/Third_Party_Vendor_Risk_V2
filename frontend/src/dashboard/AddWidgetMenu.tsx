import { useLayoutEffect, useRef } from "react";
import type { CatalogEntry } from "./widgetMeta";
import type { WidgetType } from "@/lib/types";

const EDGE = 16; // px kept clear between the menu and the screen edge (the page gutter)

/**
 * The "Add widget" dropdown. It hangs from the right edge of its button, which on
 * a narrow screen can push it past the left edge; after layout it is shifted
 * sideways by however much is needed to sit fully on screen.
 */
export function AddWidgetMenu({
  available,
  onAdd,
  onClose,
}: {
  available: CatalogEntry[];
  onAdd: (type: WidgetType) => void;
  onClose: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const place = () => {
      el.style.transform = "";
      const box = el.getBoundingClientRect();
      const screen = document.documentElement.clientWidth;
      let shift = 0;
      if (box.left < EDGE) shift = EDGE - box.left;
      else if (box.right > screen - EDGE) shift = screen - EDGE - box.right;
      if (shift) el.style.transform = `translateX(${Math.round(shift)}px)`;
    };
    place();
    window.addEventListener("resize", place);
    return () => window.removeEventListener("resize", place);
  }, [available.length]);

  return (
    <>
      <div style={{ position: "fixed", inset: 0, zIndex: 10 }} onClick={onClose} />
      <div className="addmenu" ref={ref} role="menu" aria-label="Add a widget">
        {available.map((c) => (
          <button
            key={c.type}
            type="button"
            role="menuitem"
            className="addmenu__item"
            onClick={() => onAdd(c.type)}
          >
            <c.icon size={17} />
            <span>
              <span className="addmenu__title">{c.title}</span>
              <span className="addmenu__desc">{c.description}</span>
            </span>
          </button>
        ))}
      </div>
    </>
  );
}
