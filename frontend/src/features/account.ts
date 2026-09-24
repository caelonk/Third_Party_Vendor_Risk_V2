import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { SignInMethods } from "@/lib/types";

export const MIN_PASSWORD = 8;
export const PROVIDER_NAMES: Record<string, string> = { google: "Google" };

/**
 * Which password form Settings shows:
 * - "change": the account has a password (prove the current one).
 * - "locked": created with Google and still linked — greyed out until unlinked.
 * - "create": no password and nothing linked (just unlinked) — make one now.
 */
export type PasswordMode = "change" | "locked" | "create";

export function passwordMode(methods: SignInMethods): PasswordMode {
  if (methods.has_password) return "change";
  return methods.identities.length > 0 ? "locked" : "create";
}

/** Client-side checks mirroring the API (which enforces them regardless). */
export function passwordProblems(
  mode: PasswordMode,
  v: { current: string; next: string; confirm: string },
): string | null {
  if (mode === "locked") return "Unlink Google first.";
  if (mode === "change" && !v.current) return "Enter your current password.";
  if (v.next.length < MIN_PASSWORD) return `Use at least ${MIN_PASSWORD} characters.`;
  if (v.next.length > 128) return "Use at most 128 characters.";
  if (v.next !== v.confirm) return "The new passwords don't match.";
  if (mode === "change" && v.next === v.current) {
    return "Choose a new password that differs from your current one.";
  }
  return null;
}

const KEY = ["sign-in-methods"];

export function useSignInMethods() {
  return useQuery({
    queryKey: KEY,
    queryFn: () => api.get<SignInMethods>("/me/sign-in-methods"),
  });
}

export function useUnlinkIdentity() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (provider: string) => api.del<SignInMethods>(`/me/identities/${provider}`),
    onSuccess: (methods) => qc.setQueryData(KEY, methods),
  });
}

export function useSetPassword() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { current_password?: string; new_password: string }) =>
      api.put<void>("/me/password", body),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });
}
