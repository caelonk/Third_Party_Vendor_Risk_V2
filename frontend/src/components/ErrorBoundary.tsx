import { Component, type ErrorInfo, type ReactNode } from "react";
import { TriangleAlert } from "lucide-react";

/**
 * Contains a rendering error to the page it happened on. Without this, one
 * component throwing would unmount the whole app and leave a blank screen; with
 * it the navigation stays usable and the person can reload or go elsewhere.
 * Give it a `key` that changes on navigation so moving to another page clears it.
 */
export class ErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("A page failed to render:", error, info.componentStack);
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <div className="card" role="alert">
        <div className="empty">
          <TriangleAlert />
          <div>
            <strong>This page hit a problem</strong>
            <p className="subtle" style={{ marginTop: 4, maxWidth: "46ch" }}>
              Something on it failed to display. Your data is unaffected. Reloading usually
              fixes it; the rest of the app still works from the menu.
            </p>
          </div>
          <button className="btn btn--primary" type="button" onClick={() => window.location.reload()}>
            Reload the page
          </button>
        </div>
      </div>
    );
  }
}
