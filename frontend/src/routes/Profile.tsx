import { type ChangeEvent, type FormEvent, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Upload } from "lucide-react";
import { Avatar } from "@/components/Avatar";
import { useAuth } from "@/auth/AuthProvider";
import { useOrg } from "@/org/OrgProvider";
import {
  AVATAR_TYPES,
  MAX_NAME_LENGTH,
  describeBrowser,
  fmtDateTime,
  signInMethodLabel,
  useRecentSignIns,
  useRemoveAvatar,
  useUpdateProfile,
  useUploadAvatar,
} from "@/features/profile";
import type { User } from "@/lib/types";
import { SecurityCard } from "./SecurityCard";
import "./profile.css";

function message(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}

function PhotoAndName({ user }: { user: User }) {
  const { updateUser } = useAuth();
  const upload = useUploadAvatar(updateUser);
  const remove = useRemoveAvatar(updateUser);
  const save = useUpdateProfile(updateUser);
  const picker = useRef<HTMLInputElement>(null);
  const [name, setName] = useState(user.name ?? "");
  const [saved, setSaved] = useState(false);

  // Keep the field in step if the name changes elsewhere (e.g. another tab's save).
  useEffect(() => setName(user.name ?? ""), [user.name]);

  const onPick = (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = ""; // choosing the same file again should still fire
    if (!file) return;
    remove.reset();
    upload.mutate(file);
  };

  const onSave = (e: FormEvent) => {
    e.preventDefault();
    setSaved(false);
    save.mutate(name, { onSuccess: () => setSaved(true) });
  };

  const photoBusy = upload.isPending || remove.isPending;
  const photoError = upload.error ?? remove.error;
  const unchanged = name.trim() === (user.name ?? "");

  return (
    <section className="card">
      <div className="card__header">
        <span className="card__title">Profile</span>
      </div>
      <div className="card__body profile__sections">
        <div className="profile__photo">
          <Avatar user={user} size={72} />
          <div className="profile__photo-main">
            <div className="profile__heading">Profile photo</div>
            <div className="profile__photo-actions">
              <button
                type="button"
                className="btn btn--secondary btn--sm"
                disabled={photoBusy}
                onClick={() => picker.current?.click()}
              >
                {upload.isPending ? <span className="spinner profile__spinner" /> : <Upload />}
                {user.avatar_url ? "Replace photo" : "Upload photo"}
              </button>
              {user.avatar_url && (
                <button
                  type="button"
                  className="btn btn--ghost btn--sm"
                  disabled={photoBusy}
                  onClick={() => {
                    upload.reset();
                    remove.mutate();
                  }}
                >
                  Remove
                </button>
              )}
              <input
                ref={picker}
                className="sr-only"
                type="file"
                accept={AVATAR_TYPES.join(",")}
                aria-label="Choose a profile photo"
                tabIndex={-1}
                onChange={onPick}
              />
            </div>
            <span className="field__hint">
              PNG, JPEG or WebP. It is cropped to a circle and shown to people in your
              organizations.
            </span>
            {photoError && (
              <div className="banner banner--error" role="alert">
                {message(photoError, "Could not update the photo.")}
              </div>
            )}
          </div>
        </div>

        <form className="profile__section" onSubmit={onSave} noValidate>
          <div className="field profile__name">
            <label className="field__label" htmlFor="profile-name">
              Display name
            </label>
            <div className="profile__inline">
              <input
                id="profile-name"
                className="input"
                type="text"
                autoComplete="name"
                maxLength={MAX_NAME_LENGTH}
                placeholder="Your name"
                value={name}
                onChange={(e) => {
                  setName(e.target.value);
                  setSaved(false);
                }}
              />
              <button className="btn btn--primary" type="submit" disabled={save.isPending || unchanged}>
                {save.isPending ? <span className="spinner" /> : "Save"}
              </button>
            </div>
            <span className="field__hint">
              Shown in the sidebar, member lists and the activity log. Leave it blank to show
              your email instead.
            </span>
          </div>
          {saved && <div className="banner banner--ok">Display name saved.</div>}
          {save.isError && (
            <div className="banner banner--error" role="alert">
              {message(save.error, "Could not save the name.")}
            </div>
          )}
        </form>

        <div className="profile__section">
          <dl className="kv">
            <dt>Email</dt>
            <dd className="profile__wrap">{user.email}</dd>
          </dl>
          <span className="field__hint">
            The address this account signs in with. It can't be changed here.
          </span>
        </div>
      </div>
    </section>
  );
}

function OrganizationCard() {
  const { orgs, currentOrg } = useOrg();
  if (!currentOrg) return null;
  const isAdmin = currentOrg.role === "owner" || currentOrg.role === "admin";
  const hasDetails = !!(currentOrg.employee_id || currentOrg.team);

  return (
    <section className="card">
      <div className="card__header">
        <span className="card__title">Organization</span>
      </div>
      <div className="card__body profile__section">
        <dl className="kv">
          <dt>Organization</dt>
          <dd>{currentOrg.name}</dd>
          <dt>Your role</dt>
          <dd style={{ textTransform: "capitalize" }}>{currentOrg.role}</dd>
          {currentOrg.employee_id && (
            <>
              <dt>Employee ID</dt>
              <dd className="mono">{currentOrg.employee_id}</dd>
            </>
          )}
          {currentOrg.team && (
            <>
              <dt>Team</dt>
              <dd>{currentOrg.team}</dd>
            </>
          )}
        </dl>
        {hasDetails && (
          <span className="field__hint">
            Your employee ID and team are kept by this organization's admins.
          </span>
        )}
        {!hasDetails && isAdmin && (
          <span className="field__hint">
            No employee ID or team is recorded for you here. Admins can add them for any member
            under <Link to="/settings#members">Settings &rsaquo; Members</Link>.
          </span>
        )}
        {orgs.length > 1 && (
          <span className="field__hint">
            You belong to {orgs.length} organizations. This shows {currentOrg.name}; switch
            organizations from the menu to see another.
          </span>
        )}
      </div>
    </section>
  );
}

function RecentSignIns() {
  const signIns = useRecentSignIns();
  const events = signIns.data ?? [];

  return (
    <section className="card">
      <div className="card__header">
        <span className="card__title">Recent sign-ins</span>
      </div>
      <div className="card__body profile__section">
        {signIns.isLoading ? (
          <span className="spinner" />
        ) : signIns.isError ? (
          <div className="banner banner--error" role="alert">
            Could not load your recent sign-ins.
          </div>
        ) : events.length === 0 ? (
          <p className="subtle profile__note">
            No sign-ins recorded yet. Each time you sign in from now on is listed here.
          </p>
        ) : (
          <>
            <ol className="signins">
              {events.map((e, i) => (
                <li key={`${e.created_at}-${i}`} className="signins__row">
                  <div className="signins__main">
                    <span className="signins__when">{fmtDateTime(e.created_at)}</span>
                    <span className="subtle signins__where">
                      {describeBrowser(e.user_agent)}
                      {e.ip && (
                        <>
                          {" · "}
                          <span className="mono">{e.ip}</span>
                        </>
                      )}
                    </span>
                  </div>
                  <span className="pill">{signInMethodLabel(e.method)}</span>
                </li>
              ))}
            </ol>
            <span className="field__hint">
              The last {events.length === 1 ? "time" : `${events.length} times`} this account
              signed in, newest first. If you don't recognise one, change your password.
            </span>
          </>
        )}
      </div>
    </section>
  );
}

export function Profile() {
  const { user } = useAuth();
  if (!user) return null;

  return (
    <>
      <div className="page-header">
        <div>
          <h1>Your profile</h1>
          <p>Your details, how you sign in, and your recent sign-ins.</p>
        </div>
      </div>

      <div className="profile">
        <PhotoAndName user={user} />
        <OrganizationCard />
        <SecurityCard />
        <RecentSignIns />
      </div>
    </>
  );
}
