import { googleStartUrl, useAuthProviders } from "@/features/sso";
import "./google-sign-in.css";

/** The Google "G", drawn in the current text color (the palette stays neutral). */
function GoogleMark() {
  return (
    <svg className="sso__mark" viewBox="0 0 18 18" aria-hidden="true" focusable="false">
      <path
        fill="currentColor"
        d="M17.64 9.2c0-.64-.06-1.25-.16-1.84H9v3.48h4.84a4.14 4.14 0 0 1-1.8 2.72v2.26h2.92c1.7-1.57 2.68-3.87 2.68-6.62Z"
      />
      <path
        fill="currentColor"
        d="M9 18c2.43 0 4.47-.8 5.96-2.18l-2.92-2.26c-.8.54-1.83.86-3.04.86-2.34 0-4.33-1.58-5.04-3.71H.96v2.33A9 9 0 0 0 9 18Z"
      />
      <path
        fill="currentColor"
        d="M3.96 10.71A5.41 5.41 0 0 1 3.68 9c0-.59.1-1.17.28-1.71V4.96H.96A9 9 0 0 0 0 9c0 1.45.35 2.83.96 4.04l3-2.33Z"
      />
      <path
        fill="currentColor"
        d="M9 3.58c1.32 0 2.51.45 3.44 1.35l2.58-2.59A8.65 8.65 0 0 0 9 0 9 9 0 0 0 .96 4.96l3 2.33C4.67 5.16 6.66 3.58 9 3.58Z"
      />
    </svg>
  );
}

/** "Continue with Google" plus an "or" divider — renders nothing unless the
 *  server has Google (or its development stand-in) enabled. */
export function GoogleSignIn({ next = "/" }: { next?: string }) {
  const providers = useAuthProviders();
  const google = providers.data?.find((p) => p.id === "google");
  if (!google) return null;

  return (
    <div className="sso">
      <a className="btn btn--secondary btn--block sso__btn" href={googleStartUrl(next)}>
        <GoogleMark />
        Continue with Google
      </a>
      {google.dev_stand_in && (
        <p className="sso__note">
          Development stand-in: no Google credentials are configured, so this opens a test
          sign-in page instead of Google.
        </p>
      )}
      <div className="sso__divider" role="separator">
        <span>or use your email</span>
      </div>
    </div>
  );
}
