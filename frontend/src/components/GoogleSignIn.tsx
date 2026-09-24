import googleLogo from "@/assets/google/g-logo.svg";
import { googleStartUrl, useAuthProviders } from "@/features/sso";
import "./google-sign-in.css";

/** Google's official "G" (from its pre-approved brand assets; never recolored). */
export function GoogleLogo({ size = 20 }: { size?: number }) {
  return <img className="gsi-logo" src={googleLogo} width={size} height={size} alt="" />;
}

/** "Sign in / Sign up with Google", styled to Google's branding guidelines
 *  (light or dark theme button to match the app), plus an "or" divider. Renders
 *  nothing unless the server has Google (or its development stand-in) enabled. */
export function GoogleSignIn({ mode = "signin", next = "/" }: { mode?: "signin" | "signup"; next?: string }) {
  const providers = useAuthProviders();
  const google = providers.data?.find((p) => p.id === "google");
  if (!google) return null;

  return (
    <div className="sso">
      <a className="gsi-btn" href={googleStartUrl(next)}>
        <GoogleLogo />
        <span className="gsi-btn__label">
          {mode === "signup" ? "Sign up with Google" : "Sign in with Google"}
        </span>
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
