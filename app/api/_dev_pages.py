"""The page shell for development stand-ins (the Google sign-in and Stripe
billing stand-ins). Self-contained HTML with a strict CSP, never cached, and
always labeled as a stand-in so nobody mistakes it for the real provider.
"""
from __future__ import annotations

from fastapi.responses import HTMLResponse

DEV_CSP = (
    "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; "
    "frame-ancestors 'none'; base-uri 'none'"
)

_STYLE = """
  :root { --bg:#f5f7fa; --card:#fff; --text:#1a2230; --muted:#5b6675; --border:#d9e0ea;
          --accent:#385ea3; --on-accent:#fff; --danger:#b3261e; color-scheme: light dark; }
  @media (prefers-color-scheme: dark) {
    :root { --bg:#0f141b; --card:#161c25; --text:#e6eaf0; --muted:#98a2b3; --border:#2a3240;
            --accent:#7f9fd6; --on-accent:#0f141b; --danger:#f2b8b5; } }
  * { box-sizing: border-box; }
  body { margin:0; min-height:100vh; display:flex; align-items:center; justify-content:center;
         padding:16px; background:var(--bg); color:var(--text);
         font:15px/1.5 -apple-system, "Segoe UI", Helvetica, Arial, sans-serif; }
  main { width:100%; max-width:420px; background:var(--card); border:1px solid var(--border);
         border-radius:10px; padding:28px; }
  h1 { font-size:18px; margin:0 0 6px; }
  p { margin:0 0 18px; color:var(--muted); font-size:13.5px; }
  .tag { display:inline-block; font-size:11px; font-weight:600; letter-spacing:.04em;
         text-transform:uppercase; color:var(--muted); border:1px solid var(--border);
         border-radius:999px; padding:2px 9px; margin-bottom:14px; }
  label { display:block; font-size:13px; font-weight:600; margin:0 0 6px; }
  input[type=email], input[type=text] { width:100%; height:38px; padding:0 10px; font:inherit;
         color:inherit; background:var(--bg); border:1px solid var(--border); border-radius:6px;
         margin-bottom:14px; }
  .check { display:flex; gap:8px; align-items:center; font-weight:400; margin-bottom:20px; }
  .row { display:flex; gap:10px; flex-wrap:wrap; }
  .stack { display:flex; flex-direction:column; gap:10px; }
  button, a.button { flex:1; min-height:38px; padding:8px 12px; font:inherit; font-weight:600;
           border-radius:6px; cursor:pointer; border:1px solid var(--border); background:var(--card);
           color:var(--text); text-align:center; text-decoration:none; }
  button.primary { background:var(--accent); border-color:var(--accent); color:var(--on-accent); }
  button.danger { color:var(--danger); }
  dl { display:grid; grid-template-columns:auto 1fr; gap:6px 14px; margin:0 0 20px;
       font-size:13.5px; }
  dt { color:var(--muted); } dd { margin:0; font-weight:600; }
  .notice { border:1px solid var(--border); border-radius:6px; padding:8px 12px;
            font-size:13px; margin-bottom:16px; }
  .err { color:var(--danger); }
  .mono { font-family: Consolas, Menlo, monospace; }
"""


def render(title: str, body: str, *, status_code: int = 200) -> HTMLResponse:
    """``body`` is trusted markup: callers must html-escape any values in it."""
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>{_STYLE}</style></head>
<body><main>
  <span class="tag">Development stand-in</span>
  {body}
</main></body></html>"""
    resp = HTMLResponse(page, status_code=status_code)
    resp.headers["Content-Security-Policy"] = DEV_CSP
    resp.headers["Cache-Control"] = "no-store"
    return resp
