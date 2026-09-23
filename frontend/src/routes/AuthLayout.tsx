import type { ReactNode } from "react";
import { Wordmark } from "@/components/Logo";
import { TierBadge } from "@/components/TierBadge";
import type { Tier } from "@/lib/types";
import "./auth.css";

const TIERS: Tier[] = ["Critical", "High", "Medium", "Low", "Not Assessed"];

export function AuthLayout({
  title,
  subtitle,
  children,
  footer,
}: {
  title: string;
  subtitle: string;
  children: ReactNode;
  footer: ReactNode;
}) {
  return (
    <div className="auth">
      <aside className="auth__brand">
        <Wordmark size={28} />
        <div className="auth__pitch">
          <p className="eyebrow">Third-party vulnerability risk</p>
          <h1>Continuous, honest risk scoring for the vendors you depend on.</h1>
          <p>
            Real CVE and CISA KEV data, scored on a threat &times; exposure matrix — with the
            noise, and the false comfort, stripped out.
          </p>
          <div className="auth__legend">
            {TIERS.map((t) => (
              <TierBadge key={t} tier={t} />
            ))}
          </div>
        </div>
        <p className="auth__disclaimer">
          This tool measures published vulnerabilities in vendor products. It does not measure
          whether a vendor has been breached. A high score means &ldquo;investigate,&rdquo; not
          &ldquo;compromised.&rdquo;
        </p>
      </aside>

      <main className="auth__form-wrap">
        <div className="auth__form">
          <div className="auth__mobilebrand">
            <Wordmark size={26} />
            <p>Honest risk scoring for the vendors you depend on.</p>
          </div>
          <h2>{title}</h2>
          <p className="subtle">{subtitle}</p>
          {children}
          <div className="auth__foot">{footer}</div>
        </div>
      </main>
    </div>
  );
}
