import { type FormEvent, type Ref, useRef, useState } from "react";
import { KeyRound } from "lucide-react";
import { GoogleLogo } from "@/components/GoogleSignIn";
import { Modal } from "@/components/Modal";
import {
  MIN_PASSWORD,
  PROVIDER_NAMES,
  passwordMode,
  passwordProblems,
  useSetPassword,
  useSignInMethods,
  useUnlinkIdentity,
} from "@/features/account";
import { ApiError } from "@/lib/api";
import { fmtDate } from "@/lib/format";
import type { LinkedIdentity } from "@/lib/types";

const EMPTY = { current: "", next: "", confirm: "" };

function ConnectedAccount({
  identity,
  onUnlink,
}: {
  identity: LinkedIdentity;
  onUnlink: () => void;
}) {
  const name = PROVIDER_NAMES[identity.provider] ?? identity.provider;
  return (
    <div className="security__account">
      {identity.provider === "google" ? <GoogleLogo size={18} /> : null}
      <div className="security__account-main">
        <span className="security__account-name">{name}</span>
        <span className="subtle security__account-meta">
          {identity.email ?? "Connected"} · linked {fmtDate(identity.linked_at)}
        </span>
      </div>
      <button type="button" className="btn btn--secondary btn--sm" onClick={onUnlink}>
        Unlink
      </button>
    </div>
  );
}

export function SecurityCard() {
  const methods = useSignInMethods();
  const unlink = useUnlinkIdentity();
  const setPassword = useSetPassword();
  const [confirming, setConfirming] = useState<LinkedIdentity | null>(null);
  const [values, setValues] = useState(EMPTY);
  const [formError, setFormError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const firstField = useRef<HTMLInputElement>(null);

  if (!methods.data) return null;
  const mode = passwordMode(methods.data);
  const locked = mode === "locked";
  const google = methods.data.identities.find((i) => i.provider === "google");

  const doUnlink = () => {
    if (!confirming) return;
    const provider = confirming.provider;
    const hadPassword = methods.data?.has_password ?? false;
    unlink.mutate(provider, {
      onSuccess: () => {
        setConfirming(null);
        setFormError(null);
        setNotice(
          hadPassword
            ? `${PROVIDER_NAMES[provider] ?? provider} is unlinked. Sign in with your email and password from now on.`
            : `${PROVIDER_NAMES[provider] ?? provider} is unlinked. Create a password below to finish.`,
        );
        if (!hadPassword) setTimeout(() => firstField.current?.focus(), 0);
      },
    });
  };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    setNotice(null);
    const problem = passwordProblems(mode, values);
    if (problem) {
      setFormError(problem);
      return;
    }
    setFormError(null);
    setPassword.mutate(
      {
        current_password: mode === "change" ? values.current : undefined,
        new_password: values.next,
      },
      {
        onSuccess: () => {
          setValues(EMPTY);
          setNotice(mode === "create" ? "Password created. You can now sign in with your email." : "Password changed.");
        },
        onError: (err) => setFormError(err instanceof ApiError ? err.message : "Could not save the password."),
      },
    );
  };

  const field = (
    key: keyof typeof EMPTY,
    label: string,
    autoComplete: string,
    ref?: Ref<HTMLInputElement>,
  ) => (
    <div className="field">
      <label className="field__label" htmlFor={`pw-${key}`}>
        {label}
      </label>
      <input
        id={`pw-${key}`}
        ref={ref}
        className="input"
        type="password"
        autoComplete={autoComplete}
        value={values[key]}
        onChange={(e) => setValues((v) => ({ ...v, [key]: e.target.value }))}
      />
    </div>
  );

  return (
    <section className="card">
      <div className="card__header">
        <span className="card__title">Sign-in &amp; security</span>
      </div>
      <div className="card__body security">
        <div className="security__section">
          <div className="security__heading">Connected accounts</div>
          {google ? (
            <ConnectedAccount identity={google} onUnlink={() => setConfirming(google)} />
          ) : (
            <p className="subtle security__hint">
              No Google account is connected. Signing in with Google connects it automatically.
            </p>
          )}
        </div>

        <form className="security__section" onSubmit={submit} noValidate>
          <div className="security__heading">
            {mode === "create" ? "Create a password" : "Password"}
          </div>

          {notice && <div className="banner banner--ok">{notice}</div>}
          {locked && (
            <p className="security__locked-note">
              <KeyRound size={15} aria-hidden="true" />
              <span>
                This account was created with Google, so it has no password. To create one,
                unlink Google above first.
              </span>
            </p>
          )}
          {mode === "create" && !notice && (
            <p className="subtle security__hint">
              Your account has no password yet. Create one to sign in with your email.
            </p>
          )}

          <fieldset className="security__fields" disabled={locked} aria-disabled={locked}>
            {mode === "change" && field("current", "Current password", "current-password", firstField)}
            {field(
              "next",
              mode === "change" ? "New password" : "Password",
              "new-password",
              mode === "change" ? undefined : firstField,
            )}
            {field("confirm", "Confirm password", "new-password")}
            <span className="field__hint">At least {MIN_PASSWORD} characters.</span>
            {formError && (
              <div className="banner banner--error" role="alert">
                {formError}
              </div>
            )}
            <div>
              <button className="btn btn--primary" type="submit" disabled={locked || setPassword.isPending}>
                {setPassword.isPending ? (
                  <span className="spinner" />
                ) : mode === "change" ? (
                  "Change password"
                ) : (
                  "Create password"
                )}
              </button>
            </div>
          </fieldset>
        </form>
      </div>

      <Modal open={!!confirming} onClose={() => setConfirming(null)} title="Unlink Google?">
        <p style={{ marginTop: 0 }}>
          {methods.data.has_password
            ? "You'll sign in with your email and password from now on."
            : "You'll stay signed in here. Next, create a password so you can sign in with your email."}{" "}
          <span className="subtle">
            Signing in with Google again later will reconnect it.
          </span>
        </p>
        {unlink.isError && (
          <div className="banner banner--error" role="alert" style={{ marginBottom: "var(--space-4)" }}>
            {unlink.error.message}
          </div>
        )}
        <div className="security__modal-actions">
          <button type="button" className="btn btn--ghost" onClick={() => setConfirming(null)}>
            Cancel
          </button>
          <button type="button" className="btn btn--danger" onClick={doUnlink} disabled={unlink.isPending}>
            {unlink.isPending ? <span className="spinner" /> : "Unlink Google"}
          </button>
        </div>
      </Modal>
    </section>
  );
}
