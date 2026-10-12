import { useEffect, useState } from "react";
import "./avatar.css";

export interface AvatarSubject {
  name: string | null;
  email: string;
  avatar_url?: string | null;
}

// eslint-disable-next-line react-refresh/only-export-components
export function initials(name: string | null, email: string): string {
  const parts = (name ?? "").trim().split(/\s+/).filter(Boolean);
  if (parts.length) return (parts[0][0] + (parts[1]?.[0] ?? "")).toUpperCase();
  return email.slice(0, 2).toUpperCase();
}

/** A person's photo, or their initials when they have none (or it fails to load). */
export function Avatar({ user, size = 32 }: { user: AvatarSubject; size?: number }) {
  const [failed, setFailed] = useState(false);
  const src = user.avatar_url ?? null;
  useEffect(() => setFailed(false), [src]);

  return (
    <span
      className="avatar"
      style={{ width: size, height: size, fontSize: Math.max(11, Math.round(size * 0.38)) }}
      aria-hidden="true"
    >
      {src && !failed ? (
        <img src={src} alt="" width={size} height={size} onError={() => setFailed(true)} />
      ) : (
        initials(user.name, user.email)
      )}
    </span>
  );
}
