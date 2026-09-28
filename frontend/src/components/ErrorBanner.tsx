import type { CSSProperties } from "react";
import { Link } from "react-router-dom";
import { isPlanLimit } from "@/features/billing";

/** An error message; when the API said the plan doesn't allow it (402), it also
 *  links to the plan comparison. Accepts an error object or a plain string. */
export function ErrorBanner({
  error,
  fallback = "Something went wrong.",
  style,
}: {
  error: unknown;
  fallback?: string;
  style?: CSSProperties;
}) {
  if (!error) return null;
  const text = typeof error === "string" ? error : error instanceof Error ? error.message : fallback;
  return (
    <div className="banner banner--error" role="alert" style={style}>
      <span>
        {text}
        {isPlanLimit(error) && (
          <>
            {" "}
            <Link className="banner__link" to="/settings#billing">
              See plans
            </Link>
          </>
        )}
      </span>
    </div>
  );
}
