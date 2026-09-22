import { useEffect, useRef, useState } from "react";
import { LayoutGrid, Plus, Check } from "lucide-react";
import { DashboardGrid } from "@/dashboard/DashboardGrid";
import { CATALOG } from "@/dashboard/widgetMeta";
import { MAX_WIDGETS } from "@/dashboard/constants";
import { usePreferences, useUpdatePreferences } from "@/features/preferences";
import { useOrg } from "@/org/OrgProvider";
import type { Widget, WidgetType } from "@/lib/types";
import "@/dashboard/dashboard.css";

function makeWidget(type: WidgetType): Widget {
  return { type, config: {}, expanded: false, w: 1, h: 1 };
}

export function Dashboard() {
  const { currentOrg } = useOrg();
  const { data: prefs, isLoading } = usePreferences();
  const update = useUpdatePreferences();

  const [widgets, setWidgets] = useState<Widget[]>([]);
  const [editing, setEditing] = useState(false);
  const [addOpen, setAddOpen] = useState(false);
  const loaded = useRef(false);

  // Adopt the saved layout once.
  useEffect(() => {
    if (prefs && !loaded.current) {
      loaded.current = true;
      setWidgets(prefs.dashboard_layout ?? []);
    }
  }, [prefs]);

  const persist = (next: Widget[]) => {
    setWidgets(next);
    update.mutate({ dashboard_layout: next });
  };

  const used = new Set(widgets.map((w) => w.type));
  const available = CATALOG.filter((c) => !used.has(c.type));
  const canAdd = widgets.length < MAX_WIDGETS && available.length > 0;

  const addWidget = (type: WidgetType) => {
    persist([...widgets, makeWidget(type)]);
    setAddOpen(false);
  };
  const removeWidget = (i: number) => persist(widgets.filter((_, idx) => idx !== i));
  const toggleExpand = (i: number) =>
    persist(
      widgets.map((w, idx) =>
        idx === i ? { ...w, expanded: !w.expanded, w: !w.expanded ? 2 : 1 } : w,
      ),
    );

  if (isLoading) return <div className="empty"><span className="spinner" /></div>;

  return (
    <>
      <div className="page-header">
        <div>
          <h1>Dashboard</h1>
          <p>{currentOrg?.name} &middot; your personal risk board</p>
        </div>
        <div className="row">
          {editing && canAdd && (
            <div style={{ position: "relative" }}>
              <button className="btn btn--secondary" onClick={() => setAddOpen((o) => !o)}>
                <Plus /> Add widget
              </button>
              {addOpen && (
                <>
                  <div style={{ position: "fixed", inset: 0, zIndex: 10 }} onClick={() => setAddOpen(false)} />
                  <div className="addmenu">
                    {available.map((c) => (
                      <button key={c.type} className="addmenu__item" onClick={() => addWidget(c.type)}>
                        <c.icon size={17} />
                        <span>
                          <span className="addmenu__title">{c.title}</span>
                          <span className="addmenu__desc">{c.description}</span>
                        </span>
                      </button>
                    ))}
                  </div>
                </>
              )}
            </div>
          )}
          <button
            className={editing ? "btn btn--primary" : "btn btn--secondary"}
            onClick={() => setEditing((e) => !e)}
          >
            {editing ? (
              <>
                <Check /> Done
              </>
            ) : (
              <>
                <LayoutGrid /> Customize
              </>
            )}
          </button>
        </div>
      </div>

      {widgets.length === 0 ? (
        <div className="card">
          <div className="empty">
            <LayoutGrid />
            <div>
              <strong>Build your board</strong>
              <p className="subtle" style={{ marginTop: 4, maxWidth: "42ch" }}>
                Add up to {MAX_WIDGETS} widgets — tier distribution, the risk heatmap, your renewal
                watchlist and more. Arrange them however you think.
              </p>
            </div>
            <div style={{ position: "relative" }}>
              <button
                className="btn btn--primary"
                onClick={() => {
                  setEditing(true);
                  setAddOpen(true);
                }}
              >
                <Plus /> Add a widget
              </button>
            </div>
          </div>
        </div>
      ) : (
        <DashboardGrid
          widgets={widgets}
          editing={editing}
          onReorder={persist}
          onToggleExpand={toggleExpand}
          onRemove={removeWidget}
        />
      )}

      {editing && widgets.length > 0 && (
        <p className="subtle" style={{ fontSize: "0.78rem", marginTop: "var(--space-4)" }}>
          {widgets.length}/{MAX_WIDGETS} widgets. Drag by the handle to reorder; expand any widget
          for detail.
        </p>
      )}
    </>
  );
}
