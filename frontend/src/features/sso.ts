import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { AuthProvider } from "@/lib/types";

/** Messages for the `sso_error` codes the callback sends people back with.
 *  Provider details never reach the page; they're in the server logs. */
export const SSO_ERRORS: Record<string, string> = {
  cancelled: "Google sign-in was cancelled.",
  expired: "That sign-in attempt expired or was started in another browser. Please try again.",
  unverified:
    "Your Google account's email address isn't verified, so it can't be used to sign in here.",
  disabled: "This account has been deactivated. Contact an administrator of your organization.",
  conflict:
    "This account is already linked to a different Google account. Sign in with that one, or use your password.",
  unavailable: "Google sign-in is unavailable right now. Try again, or sign in with your password.",
  failed: "Google sign-in didn't complete. Please try again.",
};

export function ssoErrorMessage(code: string | null): string | null {
  if (!code) return null;
  return SSO_ERRORS[code] ?? SSO_ERRORS.failed;
}

/** Full-page navigation target: the server sets the flow cookie and redirects
 *  to Google (or the development stand-in). */
export function googleStartUrl(next = "/"): string {
  const path = next.startsWith("/") && !next.startsWith("//") ? next : "/";
  return `/api/v1/auth/google/start?${new URLSearchParams({ next: path })}`;
}

export function useAuthProviders() {
  return useQuery({
    queryKey: ["auth-providers"],
    queryFn: () => api.get<AuthProvider[]>("/auth/providers"),
    staleTime: 5 * 60_000,
    retry: false,
  });
}
