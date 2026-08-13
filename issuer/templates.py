"""Inline HTML templates for the reviewer UI.

Kept as Python strings (no Jinja2 dep) — pages are small and rarely change.
"""

from html import escape

CSS = """
<style>
/*
   Veridict design tokens.

   The palette is shared between every page (homepage, dashboard, review,
   approve result, synthesize). Single accent is lime/forest green so the
   "Math" gradient on the headline and the "approve" affordance everywhere
   speak the same colour. Tokens are referenced everywhere — never use
   hardcoded hex outside this block.
*/
:root {
  color-scheme: light dark;
  /* Light mode (default) — clean, paper-feel */
  --fg:           #0a0a0a;
  --fg-strong:    #000000;
  --fg-muted:     #525252;
  --fg-subtle:    #888888;
  --bg:           #ffffff;
  --bg-soft:      #f5f6f8;
  --bg-card:      #ffffff;
  --bg-elev:      #fafafa;
  --border:       #e5e7eb;
  --border-strong:#d4d4d8;
  --accent:       #15803d;   /* forest green (light-mode legible) */
  --accent-hover: #166534;
  --accent-fg:    #ffffff;
  --accent-soft:  rgba(21,128,61,0.08);
  --accent-glow:  rgba(21,128,61,0.18);
  --warn:         #c2410c;   /* coral for "pain" callouts */
  --warn-soft:    rgba(194,65,12,0.10);
  --success:      #15803d;
  --success-bg:   rgba(21,128,61,0.10);
  --danger:       #b91c1c;
  --danger-bg:    rgba(185,28,28,0.08);
  --shadow:       0 1px 0 rgba(15,17,21,0.03), 0 2px 8px rgba(15,17,21,0.06);
  --grad-from:    #15803d;
  --grad-to:      #16a34a;
}
@media (prefers-color-scheme: dark) {
  :root {
    /* Dark mode — manifesto / cinematic */
    --fg:           #f5f5f5;
    --fg-strong:    #ffffff;
    --fg-muted:     #9a9a9a;
    --fg-subtle:    #6a6a6a;
    --bg:           #0a0a0a;
    --bg-soft:      #161616;
    --bg-card:      #0d0d0d;
    --bg-elev:      #1a1a1a;
    --border:       #1f1f1f;
    --border-strong:#2a2a2a;
    --accent:       #7CFF6B;   /* electric lime, only legible on dark */
    --accent-hover: #9aff8c;
    --accent-fg:    #0a0a0a;
    --accent-soft:  rgba(124,255,107,0.10);
    --accent-glow:  rgba(124,255,107,0.40);
    --warn:         #ff8a65;
    --warn-soft:    rgba(255,138,101,0.12);
    --success:      #7CFF6B;
    --success-bg:   rgba(124,255,107,0.10);
    --danger:       #ff6b6b;
    --danger-bg:    rgba(255,107,107,0.12);
    --shadow:       0 0 0 1px rgba(0,0,0,0.2), 0 4px 12px rgba(0,0,0,0.4);
    --grad-from:    #7CFF6B;
    --grad-to:      #4ade80;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
  background: var(--bg);
  color: var(--fg);
  line-height: 1.5;
}
.topbar {
  position: sticky; top: 0; z-index: 10;
  background: var(--bg);
  border-bottom: 1px solid var(--border);
  padding: 1rem 1.5rem;
  display: flex; justify-content: space-between; align-items: center;
  font-size: 0.875rem;
  backdrop-filter: saturate(160%) blur(8px);
}
.topbar .brand {
  font-weight: 600; letter-spacing: -0.005em;
  display: inline-flex; align-items: center; gap: 0.55rem;
}
.topbar .brand .logo {
  display: inline-block; width: 22px; height: 22px;
  border-radius: 6px;
  background-image: url('/static/bot-avatar.svg');
  background-size: contain;
  background-repeat: no-repeat;
  flex-shrink: 0;
}
.topbar .brand a {
  display: inline-flex; align-items: center; gap: 0.55rem;
  color: inherit; text-decoration: none;
}
.topbar .right { display: flex; gap: 1rem; align-items: center; }
.topbar .who { color: var(--fg-muted); }
.topbar a { color: var(--fg); text-decoration: none; }
.topbar a:hover { color: var(--accent); }
.container { max-width: 760px; margin: 0 auto; padding: 2.5rem 1.5rem; }
h1 { font-size: 1.75rem; font-weight: 600; margin: 0 0 0.25rem; letter-spacing: -0.02em; }
.subtitle { color: var(--fg-muted); font-size: 1rem; margin: 0 0 2rem; }
.card {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 1.5rem;
  margin: 1rem 0;
  box-shadow: var(--shadow);
}
.card.ok { border-color: var(--success); background: var(--success-bg); }
.card.err { border-color: var(--danger); background: var(--danger-bg); }
.card h3 { margin: 0 0 0.5rem; font-size: 1.1rem; }
.card.compact { padding: 0.85rem 1.1rem; }
label { display: block; font-weight: 500; font-size: 0.875rem;
        margin-bottom: 0.4rem; color: var(--fg); }
input[type=text] {
  width: 100%;
  padding: 0.6rem 0.75rem;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--bg);
  color: var(--fg);
  font: inherit;
  transition: border-color 0.15s, box-shadow 0.15s;
}
input[type=text]:focus {
  outline: none;
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-soft);
}
.btn {
  display: inline-flex; align-items: center; gap: 0.45rem;
  padding: 0.6rem 1.1rem;
  border-radius: 999px;
  background: var(--accent);
  color: var(--accent-fg);
  text-decoration: none;
  border: 1px solid transparent;
  font: inherit; font-weight: 600;
  cursor: pointer;
  transition: background 0.15s, transform 0.12s, filter 0.15s;
}
.btn:hover { background: var(--accent-hover); transform: translateY(-1px); }
.btn.large { padding: 0.78rem 1.4rem; font-size: 0.95rem; }
.btn.secondary {
  background: transparent; color: var(--fg);
  border: 1px solid var(--border-strong);
}
.btn.secondary:hover { background: var(--bg-soft); border-color: var(--accent); transform: translateY(-1px); }
.btn[disabled] { opacity: 0.5; cursor: not-allowed; transform: none; }
.btn .gh { width: 16px; height: 16px; fill: currentColor; }
.meta { color: var(--fg-muted); font-size: 0.875rem; margin: 0.5rem 0; }
.kbd {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  background: var(--bg-soft);
  border: 1px solid var(--border);
  padding: 0.1rem 0.4rem;
  border-radius: 3px;
  font-size: 0.85rem;
}
.badge {
  display: inline-block;
  font-size: 0.75rem; font-weight: 600;
  padding: 0.15rem 0.55rem; border-radius: 2em;
  vertical-align: middle;
  letter-spacing: 0.02em; text-transform: uppercase;
}
.badge.ok { background: var(--success-bg); color: var(--success); }
.badge.err { background: var(--danger-bg); color: var(--danger); }
.progress-bar {
  background: var(--bg-soft);
  border-radius: 999px;
  height: 8px;
  overflow: hidden;
  margin: 1rem 0;
}
.progress-bar > span {
  display: block; height: 100%;
  background: var(--success);
  transition: width 0.4s ease;
}
.howitworks {
  list-style: none; padding: 0; margin: 0;
  display: grid; gap: 0.75rem;
}
.howitworks li {
  display: flex; gap: 0.75rem; align-items: flex-start;
  font-size: 0.95rem; color: var(--fg-muted);
}
.howitworks li .step {
  flex-shrink: 0;
  background: var(--accent); color: var(--accent-fg);
  width: 1.5rem; height: 1.5rem; border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  font-size: 0.8rem; font-weight: 600;
}

/* Loading overlay shown during proof generation */
.overlay {
  position: fixed; inset: 0;
  background: rgba(0,0,0,0.55);
  display: none;
  align-items: center; justify-content: center;
  z-index: 50;
  backdrop-filter: blur(2px);
}
.overlay.active { display: flex; }
.overlay .panel {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 2rem 2.5rem;
  max-width: 420px; text-align: center;
  box-shadow: 0 20px 40px rgba(0,0,0,0.3);
}
.overlay h3 { margin: 0.5rem 0 0.25rem; font-size: 1.2rem; }
.overlay .step-text { color: var(--fg-muted); margin: 0; font-size: 0.9rem; }
.spinner {
  width: 40px; height: 40px;
  border: 3px solid var(--border);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: spin 0.9s linear infinite;
  margin: 0 auto;
}
@keyframes spin { to { transform: rotate(360deg); } }
</style>
"""


_GH_ICON = (
    '<svg class="gh" viewBox="0 0 16 16" aria-hidden="true">'
    '<path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59'
    '.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94'
    '-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58'
    '1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07'
    '-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15'
    '-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82'
    '.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82'
    '.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95'
    '.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38'
    'A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"/></svg>'
)


def _topbar(user: str | None) -> str:
    if not user:
        return f"""<div class="topbar">
          <span class="brand"><span class="logo"></span>Veridict</span>
        </div>"""
    return f"""<div class="topbar">
      <span class="brand"><a href="/review"><span class="logo"></span>Veridict</a></span>
      <span class="right">
        <span class="who">@{escape(user)}</span>
        <a href="/logout">Sign out</a>
      </span>
    </div>"""


def page(title: str, body: str, user: str | None = None) -> str:
    return f"""<!doctype html><html><head><meta charset=utf-8>
<title>{escape(title)}</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="icon" type="image/svg+xml" href="/favicon.svg">
<link rel="alternate icon" type="image/png" href="/favicon.ico">
<link rel="apple-touch-icon" href="/static/bot-avatar.png">
<meta name="theme-color" content="#0a0a0a" media="(prefers-color-scheme: dark)">
<meta name="theme-color" content="#ffffff" media="(prefers-color-scheme: light)">
{CSS}</head><body>{_topbar(user)}<div class="container">{body}</div></body></html>"""


def login_page(error: str | None = None) -> str:
    err = f'<div style="background:rgba(255,107,107,0.12);border:1px solid #ff6b6b;color:#ffb4b4;padding:0.8rem 1rem;border-radius:8px;max-width:560px;margin:1rem auto;font-size:0.85rem">{escape(error)}</div>' if error else ""
    return page("Veridict · Math approves the merge.", f"""
      <script>document.documentElement.classList.add('js-reveals');</script>
      <style>
        /* Landing-only container override (homepage needs full-width sections). */
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Inter", "Segoe UI", sans-serif; }}
        .topbar {{ background: transparent !important; }}
        .container {{ max-width: 100% !important; padding: 0 !important; }}

        /* ── shared landing tokens ─────────────────────────────────────── */
        .v-wrap {{ max-width: 1180px; margin: 0 auto; padding: 0 1.5rem; }}
        .v-eyebrow {{
          display:inline-flex; align-items:center; gap:0.5rem;
          font-size:0.7rem; font-weight:600; letter-spacing:0.18em;
          text-transform:uppercase; color:var(--accent);
        }}
        .v-eyebrow::before {{
          content:""; width:24px; height:1px; background:var(--accent);
        }}
        .v-h2 {{
          font-size: clamp(2rem, 4.5vw, 3.2rem);
          letter-spacing: -0.04em; line-height: 1.02;
          margin: 1rem 0 1.25rem; font-weight: 600;
          max-width: 18ch;
        }}
        .v-lede {{
          font-size: 1.05rem; line-height: 1.6;
          color: var(--fg-muted); max-width: 60ch; margin: 0;
        }}
        .v-btn {{
          display:inline-flex; align-items:center; gap:0.45rem;
          padding:0.85rem 1.4rem; border-radius:999px; font-weight:600;
          font-size:0.92rem; text-decoration:none; border:1px solid transparent;
          transition: transform 0.15s, background 0.15s, color 0.15s;
        }}
        .v-btn-primary {{ background:var(--accent); color:var(--bg); }}
        .v-btn-primary:hover {{ background:var(--accent-hover); transform: translateY(-1px); }}
        .v-btn-ghost {{ background:transparent; color:var(--fg); border-color:var(--border-strong); }}
        .v-btn-ghost:hover {{ background:var(--border); border-color:var(--border-strong); }}
        .v-btn .gh {{ width:16px; height:16px; fill:currentColor; }}

        /* ── HERO ──────────────────────────────────────────────────────── */
        .v-hero {{
          padding: 6rem 1.5rem 5rem; text-align: center;
          background:
            radial-gradient(ellipse 70% 50% at 50% 0%, var(--accent-soft), transparent 60%),
            radial-gradient(ellipse 50% 40% at 50% 100%, var(--accent-soft), transparent 65%);
          position: relative; overflow: hidden;
        }}
        .v-hero::after {{
          content:""; position:absolute; bottom:0; left:0; right:0; height:1px;
          background: linear-gradient(90deg, transparent, var(--border) 30%, var(--border) 70%, transparent);
        }}
        .v-hero .tag {{
          display:inline-flex; align-items:center; gap:0.5rem;
          padding:0.4rem 0.9rem;
          background: var(--accent-soft);
          border: 1px solid var(--accent-glow);
          border-radius:999px; font-size:0.72rem; font-weight:500;
          color:var(--accent); letter-spacing:0.06em; text-transform:uppercase;
        }}
        .v-hero .tag .pulse {{
          width:6px; height:6px; border-radius:50%; background:var(--accent);
          box-shadow: 0 0 0 4px var(--accent-glow);
          animation: vPulse 2.4s ease-in-out infinite;
        }}
        @keyframes vPulse {{
          0%,100% {{ box-shadow: 0 0 0 0 var(--accent-glow); }}
          50% {{ box-shadow: 0 0 0 6px rgba(124,255,107,0); }}
        }}
        .v-hero h1 {{
          font-size: clamp(2.6rem, 8vw, 6rem);
          line-height: 0.95;
          letter-spacing: -0.05em;
          margin: 1.8rem auto 1.5rem;
          max-width: 14ch;
          font-weight: 600;
        }}
        .v-hero h1 .accent {{ color: var(--accent); }}
        .v-hero .sublede {{
          color:var(--fg-muted); font-size:1.1rem; line-height:1.55;
          max-width: 50ch; margin: 0 auto 2.5rem;
        }}
        .v-hero .cta {{
          display:inline-flex; gap:0.75rem; flex-wrap:wrap; justify-content:center;
        }}

        /* ── MANIFESTO BLOCK ──────────────────────────────────────────── */
        .v-manifesto {{
          padding: 7rem 1.5rem; text-align: center;
          border-bottom: 1px solid var(--border);
        }}
        .v-manifesto p {{
          font-size: clamp(1.6rem, 3.8vw, 2.6rem);
          line-height: 1.18; letter-spacing: -0.03em;
          color:var(--fg); max-width: 22ch; margin: 0 auto;
          font-weight: 500;
        }}
        .v-manifesto .strike {{ color: var(--fg-subtle); }}
        .v-manifesto .accent {{ color: var(--accent); }}

        /* ── SECTION ──────────────────────────────────────────────────── */
        .v-section {{ padding: 6rem 1.5rem; border-bottom: 1px solid var(--border); }}
        .v-split {{
          display: grid; grid-template-columns: 1fr 1fr; gap: 4rem;
          align-items: center;
        }}
        @media(max-width:880px) {{ .v-split {{ grid-template-columns: 1fr; gap: 2.5rem; }} }}

        /* ── TERMINAL/CODE MOCK ───────────────────────────────────────── */
        .v-terminal {{
          background:var(--bg-card); border:1px solid var(--border);
          border-radius: 10px; overflow:hidden;
          font-family: ui-monospace, "JetBrains Mono", SFMono-Regular, Menlo, monospace;
          font-size: 0.82rem; line-height: 1.55;
        }}
        .v-terminal .bar {{
          padding: 0.7rem 1rem; background: var(--bg-elev);
          display:flex; align-items:center; gap:0.4rem;
          border-bottom: 1px solid var(--border);
        }}
        .v-terminal .bar .dot {{ width:10px; height:10px; border-radius:50%; }}
        .v-terminal .bar .red {{ background:#ff5f56; }}
        .v-terminal .bar .yellow {{ background:#ffbd2e; }}
        .v-terminal .bar .green {{ background:#27c93f; }}
        .v-terminal .bar .title {{
          margin-left: 0.6rem; color:var(--fg-subtle); font-size:0.74rem;
        }}
        .v-terminal pre {{
          padding: 1.1rem 1.25rem; margin:0; color:var(--fg);
          overflow-x: auto;
        }}
        .v-terminal .ok {{ color: var(--accent); }}
        .v-terminal .dim {{ color: var(--fg-subtle); }}
        .v-terminal .warn {{ color: #ffc66b; }}
        .v-terminal .cmd {{ color: var(--fg-subtle); }}

        /* ── PROOF RECEIPT CARD ───────────────────────────────────────── */
        .v-receipt {{
          background:var(--bg-card); border:1px solid var(--border); border-radius:14px;
          padding: 1.5rem; font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
          font-size: 0.78rem;
        }}
        .v-receipt h4 {{
          margin:0 0 1rem; font-family:inherit; font-weight:600;
          font-size: 0.78rem; letter-spacing:0.1em; color:var(--accent);
          text-transform: uppercase; display:flex; align-items:center; gap:0.5rem;
        }}
        .v-receipt h4 .badge-ok {{
          background: var(--accent-soft); color:var(--accent);
          padding: 0.15rem 0.55rem; border-radius:999px;
          font-size:0.66rem; letter-spacing: 0.08em;
        }}
        .v-receipt .row {{
          display:flex; justify-content:space-between;
          padding: 0.45rem 0; border-bottom: 1px solid var(--border);
        }}
        .v-receipt .row:last-child {{ border-bottom: none; }}
        .v-receipt .k {{ color:var(--fg-subtle); }}
        .v-receipt .v {{ color:var(--fg); text-align:right; word-break:break-all; }}

        /* ── TRUST GRID ───────────────────────────────────────────────── */
        .v-trustgrid {{
          display:grid; grid-template-columns: repeat(2,1fr); gap: 1rem;
          margin-top: 2.5rem;
        }}
        @media(max-width:720px) {{ .v-trustgrid {{ grid-template-columns: 1fr; }} }}
        .v-tc {{
          background:var(--bg-card); border:1px solid var(--border); border-radius:12px;
          padding: 1.3rem 1.5rem;
        }}
        .v-tc h4 {{
          margin:0 0 0.75rem; font-size:0.78rem; font-weight:600;
          letter-spacing:0.12em; text-transform:uppercase; color:var(--accent);
        }}
        .v-tc ul {{ margin:0; padding:0; list-style:none; font-size:0.9rem; color:var(--fg-muted); }}
        .v-tc li {{ padding: 0.3rem 0; display:flex; gap:0.55rem; align-items:flex-start; }}
        .v-tc li::before {{ flex-shrink:0; margin-top:1px; font-weight:700; }}
        .v-tc li.sees::before {{ content:"›"; color:var(--accent); }}
        .v-tc li.blind::before {{ content:"–"; color:var(--fg-subtle); }}
        .v-tc li.blind {{ color: var(--fg-subtle); }}

        /* ── HONEST LIMITS ────────────────────────────────────────────── */
        .v-limits {{
          display:grid; grid-template-columns: repeat(2, 1fr);
          gap: 1rem; margin-top: 2.5rem;
        }}
        @media(max-width:720px) {{ .v-limits {{ grid-template-columns: 1fr; }} }}
        .v-limit {{
          background:var(--bg-card); border:1px solid var(--border); border-radius:12px;
          padding:1.3rem 1.5rem;
        }}
        .v-limit .label {{
          font-size:0.7rem; font-weight:600; letter-spacing:0.14em;
          text-transform:uppercase; color:var(--warn); margin-bottom: 0.5rem;
        }}
        .v-limit h4 {{ margin:0 0 0.4rem; font-size:1rem; }}
        .v-limit p {{ margin:0; color:var(--fg-subtle); font-size:0.88rem; line-height:1.55; }}

        /* ── FOOTER CTA ───────────────────────────────────────────────── */
        .v-final {{
          padding: 8rem 1.5rem 6rem;
          text-align: center;
          background: radial-gradient(ellipse 50% 60% at 50% 60%, var(--accent-soft), transparent 65%);
          border-bottom: 1px solid var(--border);
        }}
        .v-final h2 {{
          font-size: clamp(2.4rem, 6vw, 4.5rem); line-height: 1;
          letter-spacing: -0.05em; margin: 0 auto 1rem;
          max-width: 16ch; font-weight: 600;
        }}
        .v-final .accent {{ color:var(--accent); }}
        .v-final p {{ color:var(--fg-muted); margin: 0 auto 2.5rem; max-width: 50ch; }}

        /* ── FOOTER STRIP ─────────────────────────────────────────────── */
        .v-foot {{
          padding: 2rem 1.5rem;
          display:flex; justify-content:space-between; gap:1rem; flex-wrap:wrap;
          color:var(--fg-subtle); font-size:0.78rem;
        }}
        .v-foot a {{ color:var(--fg-muted); text-decoration:none; }}
        .v-foot a:hover {{ color:var(--accent); }}
        .v-foot .sep {{ color:#222; margin: 0 0.5rem; }}

        /* ── INLINE STACK ────────────────────────────────────────────── */
        .v-pillars {{
          display:grid; grid-template-columns: repeat(3, 1fr); gap: 1rem;
          margin-top: 2.5rem;
        }}
        @media(max-width:880px) {{ .v-pillars {{ grid-template-columns: 1fr; }} }}
        .v-pill {{
          background:var(--bg-card); border:1px solid var(--border); border-radius:12px;
          padding: 1.5rem 1.6rem 1.7rem;
        }}
        .v-pill .num {{
          font-size:0.7rem; font-weight:600; letter-spacing:0.16em;
          text-transform:uppercase; color:var(--accent); margin-bottom:0.8rem;
        }}
        .v-pill h3 {{ margin: 0 0 0.5rem; font-size: 1.1rem; letter-spacing: -0.01em; }}
        .v-pill p {{ margin: 0; color: var(--fg-subtle); font-size: 0.9rem; line-height: 1.55; }}

        /* ── INCIDENTS ──────────────────────────────────────────────────── */
        .v-incidents {{
          display: grid; grid-template-columns: repeat(2, 1fr);
          gap: 1rem; margin-top: 2.5rem;
        }}
        @media(max-width:720px) {{ .v-incidents {{ grid-template-columns: 1fr; }} }}
        .v-incident {{
          background:var(--bg-card); border:1px solid var(--border); border-radius:12px;
          padding: 1.4rem 1.6rem 1.5rem;
          position: relative;
          transition: border-color 0.2s, transform 0.2s;
        }}
        .v-incident:hover {{ border-color:var(--border-strong); transform: translateY(-2px); }}
        .v-incident-tag {{
          font-family: ui-monospace, "JetBrains Mono", SFMono-Regular, monospace;
          font-size: 0.7rem; font-weight: 600;
          letter-spacing: 0.18em; text-transform: uppercase;
          color: var(--warn);
          margin-bottom: 0.85rem;
          display: inline-flex; align-items: center; gap: 0.55rem;
        }}
        .v-incident-tag::before {{
          content:""; width:6px; height:6px; border-radius:50%;
          background:var(--warn); box-shadow:0 0 0 3px var(--warn-soft);
        }}
        .v-incident-line {{
          margin: 0; color: var(--fg);
          font-size: 0.97rem; line-height: 1.6;
        }}
        .v-incident-line .q {{ color: var(--fg); font-style: italic; }}
        .v-incident-cite {{
          display: inline-block; margin-top: 0.95rem;
          color: var(--fg-subtle); text-decoration: none;
          font-size: 0.76rem; letter-spacing: 0.02em;
          transition: color 0.15s;
        }}
        .v-incident-cite:hover {{ color: var(--accent); }}
        .v-incidents-tie {{
          margin-top: 2rem;
          padding: 1.25rem 1.4rem;
          border-left: 2px solid var(--accent);
          background: linear-gradient(90deg, var(--accent-soft), transparent 70%);
          font-size: 1rem; line-height: 1.65; color: var(--fg-muted);
          border-radius: 0 8px 8px 0;
        }}
        .v-incidents-tie strong {{ color: var(--fg); }}

        /* ─────────────────────────────────────────────────────────────────
           ANIMATED PIPELINE
           A particle traverses 6 stations on an 8-second loop. Each node
           lights up as the particle passes, then settles into a "done"
           state for the rest of the cycle. Reduced-motion users get a
           static "done" snapshot.
           ───────────────────────────────────────────────────────────────── */
        .v-flow-wrap {{
          background:
            radial-gradient(ellipse 60% 40% at 50% 50%, var(--accent-soft), transparent 70%);
          padding: 4rem 0 3rem;
          border-radius: 16px;
          margin-top: 2.5rem;
          border: 1px solid var(--border);
          position: relative;
          overflow: hidden;
        }}
        .v-flow {{
          position: relative;
          padding: 0 2.5rem;
        }}
        .v-flow-track {{
          position: absolute;
          left: 2.5rem; right: 2.5rem;
          top: 36px; height: 2px;
          background: var(--border);
          border-radius: 1px;
          overflow: visible;
        }}
        .v-flow-fill {{
          position: absolute; inset: 0 100% 0 0;
          background: linear-gradient(90deg, transparent, var(--accent));
          animation: vFlowFill 8s ease-in-out infinite;
          box-shadow: 0 0 8px var(--accent-glow);
        }}
        @keyframes vFlowFill {{
          0%      {{ right: 100%; opacity: 0; }}
          5%      {{ opacity: 1; }}
          90%     {{ right: 0%;  opacity: 1; }}
          95%     {{ right: 0%;  opacity: 0.6; }}
          100%    {{ right: 100%; opacity: 0; }}
        }}
        .v-flow-particle {{
          position: absolute; top: 36px; left: 0;
          width: 14px; height: 14px;
          background: var(--accent);
          border-radius: 50%;
          transform: translate(-50%, -50%);
          box-shadow: 0 0 18px 4px var(--accent-glow);
          animation: vFlowParticle 8s ease-in-out infinite;
          z-index: 2;
        }}
        @keyframes vFlowParticle {{
          0%   {{ left: 8%;   opacity: 0; }}
          5%   {{ left: 8%;   opacity: 1; }}
          18%  {{ left: 26%;  opacity: 1; }}
          35%  {{ left: 42%;  opacity: 1; }}
          52%  {{ left: 58%;  opacity: 1; }}
          69%  {{ left: 74%;  opacity: 1; }}
          86%  {{ left: 92%;  opacity: 1; }}
          92%  {{ left: 92%;  opacity: 1; }}
          98%  {{ left: 92%;  opacity: 0; }}
          100% {{ left: 92%;  opacity: 0; }}
        }}
        .v-flow-nodes {{
          display: grid;
          grid-template-columns: repeat(6, 1fr);
          position: relative; z-index: 1;
          padding: 0 0.5rem;
        }}
        .v-fnode {{
          text-align: center;
          padding: 0 0.4rem;
        }}
        .v-fnode-dot {{
          width: 70px; height: 70px;
          margin: 0 auto;
          background: var(--bg-card);
          border: 2px solid var(--border);
          border-radius: 50%;
          display: flex; align-items: center; justify-content: center;
          color: var(--fg-subtle); /* SVG stroke inherits */
          transition: none; /* let keyframes own visual changes */
          position: relative;
        }}
        .v-fnode-dot svg {{ display: block; }}
        .v-fnode-dot::after {{
          content: "";
          position: absolute; inset: -6px;
          border-radius: 50%;
          border: 2px solid transparent;
          opacity: 0;
        }}
        .v-fnode-label {{
          margin-top: 0.85rem;
          font-size: 0.82rem; font-weight: 600;
          letter-spacing: 0.02em;
        }}
        .v-fnode-sub {{
          margin-top: 0.2rem;
          font-size: 0.72rem; color:var(--fg-subtle);
          line-height: 1.4;
        }}

        /* Each node has its own keyframe so we can control activation timing */
        .v-fnode-1 .v-fnode-dot {{ animation: vNode1 8s ease-in-out infinite; }}
        .v-fnode-2 .v-fnode-dot {{ animation: vNode2 8s ease-in-out infinite; }}
        .v-fnode-3 .v-fnode-dot {{ animation: vNode3 8s ease-in-out infinite; }}
        .v-fnode-4 .v-fnode-dot {{ animation: vNode4 8s ease-in-out infinite; }}
        .v-fnode-5 .v-fnode-dot {{ animation: vNode5 8s ease-in-out infinite; }}
        .v-fnode-6 .v-fnode-dot {{ animation: vNode6 8s ease-in-out infinite; }}

        @keyframes vNode1 {{
          0%, 3% {{ border-color:var(--border); background:var(--bg-card); color:var(--fg-subtle); transform: scale(1); box-shadow:none; }}
          8% {{ border-color:var(--accent); color:var(--accent); transform: scale(1.12); box-shadow: 0 0 24px 4px var(--accent-glow); }}
          14%, 90% {{ border-color: var(--accent-glow); color: var(--accent); transform: scale(1); box-shadow:none; }}
          100% {{ border-color:var(--border); background:var(--bg-card); color:var(--fg-subtle); }}
        }}
        @keyframes vNode2 {{
          0%, 16% {{ border-color:var(--border); background:var(--bg-card); color:var(--fg-subtle); transform: scale(1); box-shadow:none; }}
          22% {{ border-color:var(--accent); color:var(--accent); transform: scale(1.12); box-shadow: 0 0 24px 4px var(--accent-glow); }}
          28%, 90% {{ border-color: var(--accent-glow); color: var(--accent); transform: scale(1); box-shadow:none; }}
          100% {{ border-color:var(--border); background:var(--bg-card); color:var(--fg-subtle); }}
        }}
        @keyframes vNode3 {{
          0%, 33% {{ border-color:var(--border); background:var(--bg-card); color:var(--fg-subtle); transform: scale(1); box-shadow:none; }}
          39% {{ border-color:var(--accent); color:var(--accent); transform: scale(1.12); box-shadow: 0 0 24px 4px var(--accent-glow); }}
          45%, 90% {{ border-color: var(--accent-glow); color: var(--accent); transform: scale(1); box-shadow:none; }}
          100% {{ border-color:var(--border); background:var(--bg-card); color:var(--fg-subtle); }}
        }}
        @keyframes vNode4 {{
          0%, 50% {{ border-color:var(--border); background:var(--bg-card); color:var(--fg-subtle); transform: scale(1); box-shadow:none; }}
          56% {{ border-color:var(--accent); color:var(--accent); transform: scale(1.12); box-shadow: 0 0 24px 4px var(--accent-glow); }}
          62%, 90% {{ border-color: var(--accent-glow); color: var(--accent); transform: scale(1); box-shadow:none; }}
          100% {{ border-color:var(--border); background:var(--bg-card); color:var(--fg-subtle); }}
        }}
        @keyframes vNode5 {{
          0%, 67% {{ border-color:var(--border); background:var(--bg-card); color:var(--fg-subtle); transform: scale(1); box-shadow:none; }}
          73% {{ border-color:var(--accent); color:var(--accent); transform: scale(1.12); box-shadow: 0 0 24px 4px var(--accent-glow); }}
          79%, 90% {{ border-color: var(--accent-glow); color: var(--accent); transform: scale(1); box-shadow:none; }}
          100% {{ border-color:var(--border); background:var(--bg-card); color:var(--fg-subtle); }}
        }}
        @keyframes vNode6 {{
          0%, 84% {{ border-color:var(--border); background:var(--bg-card); color:var(--fg-subtle); transform: scale(1); box-shadow:none; }}
          89% {{ border-color:var(--accent); color:var(--bg); transform: scale(1.18); box-shadow: 0 0 32px 8px var(--accent-glow); background: var(--accent-glow); }}
          93%, 100% {{ border-color: var(--accent-glow); background: var(--accent-soft); color:var(--accent); transform: scale(1); box-shadow:none; }}
        }}

        @media (prefers-reduced-motion: reduce) {{
          .v-flow-fill, .v-flow-particle, .v-fnode-dot {{ animation: none !important; }}
          .v-flow-fill {{ right: 0; opacity: 1; }}
          .v-fnode-dot {{
            border-color: var(--accent-glow) !important;
            color: var(--accent) !important;
          }}
          .v-flow-particle {{ display: none; }}
        }}

        @media (max-width: 720px) {{
          .v-flow-nodes {{ grid-template-columns: repeat(3, 1fr); row-gap: 1.5rem; }}
          .v-flow-track, .v-flow-fill, .v-flow-particle {{ display: none; }}
        }}

        /* ─────────────────────────────────────────────────────────────────
           LIVE-TYPING TERMINAL
           Each line reveals sequentially with a typewriter cursor. The full
           cycle runs once when first revealed (via IntersectionObserver).
           ───────────────────────────────────────────────────────────────── */
        .v-terminal pre.live {{
          padding: 1.1rem 1.25rem;
        }}
        .v-terminal pre.live .line {{
          display: block;
          opacity: 0;
          white-space: pre;
        }}
        .v-terminal pre.live.run .line {{
          animation: vTypeLine 0.4s ease-out forwards;
        }}
        .v-terminal pre.live.run .line:nth-child(1) {{ animation-delay: 0.05s; }}
        .v-terminal pre.live.run .line:nth-child(2) {{ animation-delay: 0.55s; }}
        .v-terminal pre.live.run .line:nth-child(3) {{ animation-delay: 1.1s; }}
        .v-terminal pre.live.run .line:nth-child(4) {{ animation-delay: 1.65s; }}
        .v-terminal pre.live.run .line:nth-child(5) {{ animation-delay: 2.2s; }}
        .v-terminal pre.live.run .line:nth-child(6) {{ animation-delay: 2.75s; }}
        .v-terminal pre.live.run .line:nth-child(7) {{ animation-delay: 3.4s; }}
        .v-terminal pre.live.run .line:nth-child(8) {{ animation-delay: 3.9s; }}
        @keyframes vTypeLine {{
          0%   {{ opacity: 0; transform: translateY(2px); }}
          100% {{ opacity: 1; transform: translateY(0); }}
        }}
        .v-cursor {{
          display: inline-block;
          width: 6px; height: 1em;
          vertical-align: -2px;
          background: var(--accent);
          animation: vCursor 1s steps(2) infinite;
          margin-left: 2px;
        }}
        @keyframes vCursor {{ 50% {{ opacity: 0; }} }}

        /* ─────────────────────────────────────────────────────────────────
           SCROLL REVEAL
           Sections fade-up when they enter the viewport. The html.js-reveals
           guard means: no JS → everything visible by default; JS present →
           hide until IntersectionObserver flips `.in`.
           ───────────────────────────────────────────────────────────────── */
        .v-reveal {{
          transition: opacity 0.7s ease, transform 0.7s ease;
        }}
        html.js-reveals .v-reveal {{
          opacity: 0;
          transform: translateY(18px);
        }}
        html.js-reveals .v-reveal.in {{ opacity: 1; transform: translateY(0); }}
        @media (prefers-reduced-motion: reduce) {{
          html.js-reveals .v-reveal {{ opacity: 1 !important; transform: none !important; }}
        }}

        /* ── personal signature ─────────────────────────────────────────── */
        .v-sig {{
          display: flex; align-items: center; justify-content: center;
          gap: 0.4rem;
          margin: 1.75rem auto 0;
          font-style: italic; color:var(--fg-subtle); font-size: 0.78rem;
          letter-spacing: 0.01em;
        }}
        .v-sig .heart {{
          display:inline-block;
          color:#ff6b9b;
          animation: vHeart 1.6s ease-in-out infinite;
        }}
        @keyframes vHeart {{
          0%,100% {{ transform: scale(1); }}
          50% {{ transform: scale(1.25); }}
        }}
      </style>

      {err}

      <!-- ─── HERO ──────────────────────────────────────────── -->
      <section class="v-hero">
        <div class="v-wrap">
          <h1>AI writes the code.<br><span class="accent">Math</span> approves the merge.</h1>
          <p class="sublede">
            Veridict is a merge gate for synthesized code. Three formal proofs
            verify the PR. One ZK signature authorizes it. Zero identities revealed.
          </p>
          <div class="cta">
            <a class="v-btn v-btn-primary" href="/login">{_GH_ICON} Sign in with GitHub</a>
            <a class="v-btn v-btn-ghost" href="#how">See how →</a>
          </div>
        </div>
      </section>

      <!-- ─── MANIFESTO ───────────────────────────────────────── -->
      <section class="v-manifesto">
        <div class="v-wrap v-reveal">
          <p>
            <span class="strike">Vibe-coded code</span> shouldn't merge on vibes.<br>
            It should merge on <span class="accent">proof.</span>
          </p>
        </div>
      </section>

      <!-- ─── WHY (incidents) ─────────────────────────────────── -->
      <section class="v-section">
        <div class="v-wrap v-reveal">
          <span class="v-eyebrow">Why we built this</span>
          <h2 class="v-h2">Open source is leaking trust.</h2>
          <p class="v-lede">Four incidents. One pattern. The same architectural
             hole shows up over and over again, in projects that have nothing
             else in common.</p>
          <div class="v-incidents">

            <article class="v-incident">
              <div class="v-incident-tag">bincode · 2024</div>
              <p class="v-incident-line">
                One maintainer rewrote git history while migrating off GitHub.
                The community asked questions. The questions became doxxing.
                The project shut down permanently.
                <span class="q">There is no 1.3.4.</span>
              </p>
              <a class="v-incident-cite" href="https://www.reddit.com/r/rust/comments/1pnz1iz/bincode_development_has_ceased_permanently/" target="_blank" rel="noopener">r/rust thread →</a>
            </article>

            <article class="v-incident">
              <div class="v-incident-tag">xz-utils · 2024</div>
              <p class="v-incident-line">
                "Jia Tan" earned maintainer status over two years, then shipped
                a backdoor that nearly compromised sshd on every major Linux
                distro. <span class="q">Caught by accident</span>, weeks before
                stable release.
              </p>
              <a class="v-incident-cite" href="https://en.wikipedia.org/wiki/XZ_Utils_backdoor" target="_blank" rel="noopener">post-mortem →</a>
            </article>

            <article class="v-incident">
              <div class="v-incident-tag">curl · 2024</div>
              <p class="v-incident-line">
                <span class="q">"My job is increasingly fact-checking the AI,"</span>
                wrote Daniel Stenberg. Open-source maintainers are drowning in
                plausible AI PRs that pass surface checks and fail on
                invariants.
              </p>
              <a class="v-incident-cite" href="https://daniel.haxx.se/blog/" target="_blank" rel="noopener">Stenberg's blog →</a>
            </article>

            <article class="v-incident">
              <div class="v-incident-tag">vibe-coding · 2025</div>
              <p class="v-incident-line">
                Karpathy coined it. The hackathon brief quoted the discomfort:
                <span class="q">"we have no way of knowing if what we're
                vibecoding does what we think it does."</span> The practice
                went mainstream anyway.
              </p>
              <a class="v-incident-cite" href="https://apartresearch.com/sprints/secure-program-synthesis-hackathon-2026-05-22-to-2026-05-24" target="_blank" rel="noopener">hackathon brief →</a>
            </article>

          </div>
          <div class="v-incidents-tie">
            Different incidents. Same shape. <strong>Identity-coupled trust at
            the centre</strong>, <strong>no formal gate before approval</strong>,
            and reviewers paying the cost in burnout, doxxing, or undetected
            backdoors.
          </div>
        </div>
      </section>

      <!-- ─── PILLARS ─────────────────────────────────────────── -->
      <section class="v-section" id="how">
        <div class="v-wrap">
          <span class="v-eyebrow">The flow</span>
          <h2 class="v-h2">Three steps. One signature.</h2>
          <p class="v-lede">No checklists. No vibes. Each PR walks the same path
             from English spec to anonymous merge approval, and the issuer
             refuses to sign if any of the three formal layers fails.</p>
          <div class="v-pillars">
            <div class="v-pill">
              <div class="num">01 / Synthesis</div>
              <h3>Spec in. Three artifacts out.</h3>
              <p>Claude turns your spec into an implementation, a pytest suite,
                 and a Z3 invariant file. The bot opens the PR for you.</p>
            </div>
            <div class="v-pill">
              <div class="num">02 / Verification</div>
              <h3>Three layers. No vibes.</h3>
              <p>mypy checks types. pytest checks behaviour. Z3 checks
                 invariants symbolically. Any failure → no credential.</p>
            </div>
            <div class="v-pill">
              <div class="num">03 / Anonymous Approval</div>
              <h3>ZK proof in ~10s.</h3>
              <p>A Longfellow proof replaces your identity with a stable
                 per-PR pseudonym. N proofs land → merge button unlocks.</p>
            </div>
          </div>

          <!-- ─── ANIMATED PIPELINE ─── -->
          <div class="v-flow-wrap v-reveal">
            <div class="v-flow">
              <div class="v-flow-track">
                <div class="v-flow-fill"></div>
              </div>
              <div class="v-flow-particle"></div>
              <div class="v-flow-nodes">
                <div class="v-fnode v-fnode-1">
                  <div class="v-fnode-dot">
                    <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                         stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">
                      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
                      <polyline points="14 2 14 8 20 8"/>
                      <line x1="8" y1="13" x2="16" y2="13"/>
                      <line x1="8" y1="17" x2="13" y2="17"/>
                    </svg>
                  </div>
                  <div class="v-fnode-label">Spec</div>
                  <div class="v-fnode-sub">English</div>
                </div>
                <div class="v-fnode v-fnode-2">
                  <div class="v-fnode-dot">
                    <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                         stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">
                      <path d="M9.5 2 L11 6 L15 7.5 L11 9 L9.5 13 L8 9 L4 7.5 L8 6 Z"/>
                      <path d="M18 14 l1 2.5 l2.5 1 l-2.5 1 l-1 2.5 l-1 -2.5 l-2.5 -1 l2.5 -1 Z"/>
                      <path d="M5 17 l0.6 1.6 L7 19.2 l-1.4 0.6 L5 21.4 L4.4 19.8 L3 19.2 l1.4 -0.6 Z"/>
                    </svg>
                  </div>
                  <div class="v-fnode-label">Synth</div>
                  <div class="v-fnode-sub">Claude</div>
                </div>
                <div class="v-fnode v-fnode-3">
                  <div class="v-fnode-dot">
                    <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                         stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                      <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/>
                      <polyline points="22 4 12 14.01 9 11.01"/>
                    </svg>
                  </div>
                  <div class="v-fnode-label">Verify</div>
                  <div class="v-fnode-sub">mypy · pytest · z3</div>
                </div>
                <div class="v-fnode v-fnode-4">
                  <div class="v-fnode-dot">
                    <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                         stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">
                      <rect x="3" y="4" width="18" height="16" rx="2"/>
                      <circle cx="9" cy="11" r="2.5"/>
                      <line x1="14" y1="10" x2="19" y2="10"/>
                      <line x1="14" y1="13" x2="17" y2="13"/>
                      <path d="M5 17.2c.7-1.5 2.3-2.5 4-2.5s3.3 1 4 2.5"/>
                    </svg>
                  </div>
                  <div class="v-fnode-label">Credential</div>
                  <div class="v-fnode-sub">MDOC bound to SHA</div>
                </div>
                <div class="v-fnode v-fnode-5">
                  <div class="v-fnode-dot">
                    <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                         stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">
                      <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
                      <rect x="9" y="10" width="6" height="6" rx="1"/>
                      <path d="M10 10V8a2 2 0 0 1 4 0v2"/>
                    </svg>
                  </div>
                  <div class="v-fnode-label">ZK Proof</div>
                  <div class="v-fnode-sub">Longfellow · 10s</div>
                </div>
                <div class="v-fnode v-fnode-6">
                  <div class="v-fnode-dot">
                    <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                         stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                      <circle cx="18" cy="18" r="3"/>
                      <circle cx="6" cy="6" r="3"/>
                      <path d="M6 21V9a9 9 0 0 0 9 9"/>
                    </svg>
                  </div>
                  <div class="v-fnode-label">Merge</div>
                  <div class="v-fnode-sub">Gate unlocks</div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      <!-- ─── VERIFICATION SHOWCASE (live-typing terminal) ─────── -->
      <section class="v-section">
        <div class="v-wrap v-split">
          <div class="v-reveal">
            <span class="v-eyebrow">Verification, in the open</span>
            <h2 class="v-h2">If the spec doesn't hold, no proof exists.</h2>
            <p class="v-lede">The issuer runs mypy, pytest, and Z3 against the
               PR before minting a credential. Failures break the chain. There
               is no "force-approve."</p>
          </div>
          <div class="v-terminal v-reveal" data-typer>
            <div class="bar">
              <span class="dot red"></span><span class="dot yellow"></span><span class="dot green"></span>
              <span class="title">issuer.spec_check · PR #11</span>
            </div>
            <pre class="live"><span class="line"><span class="cmd">$ veridict verify pull/11</span></span><span class="line"><span class="dim">→ fetching files@a8c4f2…</span></span><span class="line"><span class="ok">✓ mypy</span>      <span class="dim">0 errors</span></span><span class="line"><span class="ok">✓ pytest</span>    <span class="dim">14 passed in 0.34s</span></span><span class="line"><span class="ok">✓ z3</span>        <span class="dim">all invariants UNSAT for negation</span></span><span class="line"> </span><span class="line"><span class="ok">credential issued</span> <span class="dim">→ valid 10m</span></span><span class="line"><span class="dim">bound to a8c4f2 · role=maintainer</span><span class="v-cursor"></span></span></pre>
          </div>
        </div>
      </section>

      <!-- ─── ANONYMITY SHOWCASE (proof receipt) ───────────────── -->
      <section class="v-section">
        <div class="v-wrap v-split">
          <div class="v-receipt v-reveal">
            <h4>ZK Proof Receipt <span class="badge-ok">verified</span></h4>
            <div class="row"><span class="k">circuit_id</span><span class="v">3f8c…0192</span></div>
            <div class="row"><span class="k">size</span><span class="v">361,408 bytes</span></div>
            <div class="row"><span class="k">prover</span><span class="v">10.4 s</span></div>
            <div class="row"><span class="k">verifier</span><span class="v">7.1 s</span></div>
            <div class="row"><span class="k">transcript</span><span class="v">8217d4…ae5b</span></div>
            <div class="row"><span class="k">pseudonym</span><span class="v">@reviewer-a7c2f3</span></div>
            <div class="row"><span class="k">identity</span><span class="v">never disclosed</span></div>
          </div>
          <div class="v-reveal">
            <span class="v-eyebrow">Anonymity, by construction</span>
            <h2 class="v-h2">Reviewers prove. Identities disappear.</h2>
            <p class="v-lede">Every approval is a 360 KB Longfellow proof that
               you hold a credential. The PR author, the bot, and the audit
               trail see a pseudonym, not a face. The proof, not the person,
               speaks.</p>
          </div>
        </div>
      </section>

      <!-- ─── TRUST MATRIX ─────────────────────────────────────── -->
      <section class="v-section">
        <div class="v-wrap v-reveal">
          <span class="v-eyebrow">Trust model</span>
          <h2 class="v-h2">Who sees what.</h2>
          <p class="v-lede">Anonymity is toward the verifier: CI, the PR author,
             and the audit trail. The issuer still sees your OAuth identity at
             credential time. We say so out loud.</p>
          <div class="v-trustgrid">
            <div class="v-tc">
              <h4>Reviewer</h4>
              <ul>
                <li class="sees">Own credential, own proof</li>
                <li class="sees">Spec-check result for the PR</li>
                <li class="blind">Other reviewers' identities</li>
              </ul>
            </div>
            <div class="v-tc">
              <h4>Issuer</h4>
              <ul>
                <li class="sees">OAuth identity (credential time)</li>
                <li class="sees">Spec-check result</li>
                <li class="blind">How reviewers voted</li>
              </ul>
            </div>
            <div class="v-tc">
              <h4>Verifier / Backend</h4>
              <ul>
                <li class="sees">Proofs, pseudonyms, approval counts</li>
                <li class="sees">Posts bot comments + commit status</li>
                <li class="blind">Reviewer identities</li>
              </ul>
            </div>
            <div class="v-tc">
              <h4>PR author + GitHub UI</h4>
              <ul>
                <li class="sees">Pseudonyms + reputation chips</li>
                <li class="sees">Commit status (N / required)</li>
                <li class="blind">Reviewer identities</li>
              </ul>
            </div>
          </div>
        </div>
      </section>

      <!-- ─── HONEST LIMITS ────────────────────────────────────── -->
      <section class="v-section">
        <div class="v-wrap v-reveal">
          <span class="v-eyebrow">What this isn't</span>
          <h2 class="v-h2">We don't pretend to be production.</h2>
          <p class="v-lede">A weekend prototype is allowed limits, as long as
             it names them. Here are ours.</p>
          <div class="v-limits">
            <div class="v-limit">
              <div class="label">Anonymity</div>
              <h4>No nullifier yet.</h4>
              <p>A reviewer with two sessions can sign two approvals on one PR.
                 They look like two pseudonyms. Production fix: derive a blinded
                 ID inside the ZK circuit.</p>
            </div>
            <div class="v-limit">
              <div class="label">Key custody</div>
              <h4>Issuer mints the device key.</h4>
              <p>For demo speed. A real deployment would generate the device
                 key in the browser so the issuer never sees it.</p>
            </div>
            <div class="v-limit">
              <div class="label">Spec coverage</div>
              <h4>Python only, for now.</h4>
              <p>mypy + pytest + Z3 only run on <code>.py</code> files. Non-Python
                 PRs pass through unverified. Dafny, Rust, Lean are obvious
                 next stops.</p>
            </div>
            <div class="v-limit">
              <div class="label">Comments</div>
              <h4>Single bot account.</h4>
              <p>Every anonymous approval posts as <code>@anonymous-review-bot</code>.
                 Pseudonyms + identicons inside the comment do the
                 distinguishing.</p>
            </div>
          </div>
        </div>
      </section>

      <!-- ─── FINAL CTA ────────────────────────────────────────── -->
      <section class="v-final">
        <div class="v-wrap v-reveal">
          <h2>Sign in. <span class="accent">Approve.</span> Disappear.</h2>
          <p>Try Veridict on a real PR. The demo repo is wired up with branch
             protection, and your anonymous approval flips the gate.</p>
          <a class="v-btn v-btn-primary" href="/login">{_GH_ICON} Sign in with GitHub</a>
          <div class="v-sig">
            built in 72 hours <span class="heart">♥</span> by Sumit · solo · no caffeine spared
          </div>
        </div>
      </section>

      <!-- ─── FOOTER ───────────────────────────────────────────── -->
      <footer class="v-foot">
        <div>
          Built for
          <a href="https://apartresearch.com/sprints/secure-program-synthesis-hackathon-2026-05-22-to-2026-05-24" target="_blank">Secure Program Synthesis · May 2026</a>
          <span class="sep">·</span>Tracks 2 + 3<span class="sep">·</span>Solo: Sumit Vekariya
        </div>
        <div>
          Longfellow ZK<span class="sep">·</span>Claude<span class="sep">·</span>GitHub Apps
          <span class="sep">·</span>
          <a href="https://github.com/Zkred/veridict" target="_blank">Source</a>
        </div>
      </footer>

      <script>
        // Reveal elements on scroll + kick off live-typing once visible.
        (function() {{
          const revealObs = new IntersectionObserver((entries) => {{
            entries.forEach(e => {{
              if (e.isIntersecting) {{
                e.target.classList.add('in');
                if (e.target.matches('[data-typer], [data-typer] *')) {{
                  const pre = e.target.matches('[data-typer]')
                    ? e.target.querySelector('pre.live')
                    : null;
                  if (pre) pre.classList.add('run');
                }}
                revealObs.unobserve(e.target);
              }}
            }});
          }}, {{ threshold: 0.18 }});
          document.querySelectorAll('.v-reveal').forEach(el => revealObs.observe(el));
        }})();
      </script>
    """)


def dashboard_page(login: str, role: str, org: str, message: str | None = None,
                   access_type: str = "org") -> str:
    msg = f'<div class="card err compact">{escape(message)}</div>' if message else ""
    if org and org != "—":
        if access_type == "collaborator":
            access_line = (f'Collaborator on <span class="kbd">{escape(org)}</span>'
                           f' &nbsp;<span class="badge" style="background:var(--bg-soft);color:var(--fg-muted)">outside contributor</span>')
        else:
            access_line = (f'Member of <span class="kbd">{escape(org)}</span>'
                           f' &nbsp;<span class="badge ok">{escape(role)}</span>')
    else:
        access_line = 'Load a PR below — access is verified per repo'
    return page("Review a PR", f"""
        <h1>Review a PR</h1>
        <p class="subtitle">{access_line}. Your identity stays with the issuer.</p>
        {msg}
        <div class="card">
          <form method="get" action="/review/load" id="load-form">
            <label for="pr">Pull request</label>
            <input type="text" id="pr" name="pr"
                   placeholder="https://github.com/owner/repo/pull/42"
                   autocomplete="off" autofocus required>
            <p class="meta">Paste the PR URL, or use <span class="kbd">owner/repo/N</span>.
               You'll see the diff next, then approve anonymously.</p>
            <button class="btn large" type="submit">Load PR &amp; review</button>
          </form>
        </div>
        <div class="card" style="margin-top:1rem; border-style: dashed;">
          <h3 style="margin-top:0; font-size:1rem;">Synthesize AI code</h3>
          <p class="meta" style="margin:0 0 0.85rem">Describe what to build. Claude generates the code
             and tests, creates a GitHub PR, and runs mypy + pytest automatically
             before you can approve.</p>
          <a class="btn secondary" href="/synthesize">Synthesize with AI &rarr;</a>
        </div>
    """, user=login)


def _diff_html(patch: str) -> str:
    if not patch:
        return '<p class="meta" style="margin: 0.5rem 1rem">(no inline diff — binary or too large)</p>'
    out = []
    for line in patch.split("\n"):
        if line.startswith("@@"):
            cls = "hunk"
        elif line.startswith("+") and not line.startswith("+++"):
            cls = "add"
        elif line.startswith("-") and not line.startswith("---"):
            cls = "del"
        else:
            cls = "ctx"
        out.append(f'<span class="ln {cls}">{escape(line) or "&nbsp;"}</span>')
    return f'<pre class="diff">{"".join(out)}</pre>'


def _file_status_badge(status: str) -> str:
    cls = {
        "added": "ok", "modified": "", "removed": "err",
        "renamed": "", "changed": "",
    }.get(status, "")
    return f'<span class="badge {cls}">{escape(status)}</span>'


def _spec_check_banner(result: dict) -> str:
    """Green/red banner showing mypy + pytest result. Empty string if skipped."""
    if result.get("skipped"):
        return ""
    if result.get("passed"):
        chips = []
        if result.get("mypy_ok"):
            chips.append("mypy ✓")
        if result.get("has_tests") and result.get("pytest_ok"):
            chips.append("pytest ✓")
        elif not result.get("has_tests"):
            chips.append("no tests")
        if result.get("has_z3") and result.get("z3_ok"):
            chips.append("z3 ✓")
        n = result.get("files_checked", 0)
        chip_str = " &nbsp;·&nbsp; ".join(chips)
        return (
            f'<div class="card ok compact" style="display:flex;align-items:center;'
            f'gap:0.85rem;margin-bottom:1rem;">'
            f'<strong>&#10003; Spec check passed</strong>'
            f'<span class="meta" style="margin:0">{chip_str} &nbsp;·&nbsp; '
            f'{n} Python file(s) verified</span>'
            f'</div>'
        )
    # Failed
    mypy_details = ""
    if not result.get("mypy_ok", True) and result.get("mypy_output"):
        mypy_details = (
            '<details style="margin-top:0.5rem">'
            '<summary style="cursor:pointer;font-size:0.85rem">mypy errors</summary>'
            f'<pre style="font-size:0.78rem;overflow:auto;margin:0.4rem 0 0;'
            f'background:var(--bg-soft);padding:0.5rem;border-radius:4px">'
            f'{escape(result["mypy_output"])}</pre></details>'
        )
    pytest_details = ""
    if not result.get("pytest_ok", True) and result.get("pytest_output"):
        pytest_details = (
            '<details style="margin-top:0.5rem">'
            '<summary style="cursor:pointer;font-size:0.85rem">pytest output</summary>'
            f'<pre style="font-size:0.78rem;overflow:auto;margin:0.4rem 0 0;'
            f'background:var(--bg-soft);padding:0.5rem;border-radius:4px">'
            f'{escape(result["pytest_output"])}</pre></details>'
        )
    z3_details = ""
    if not result.get("z3_ok", True) and result.get("z3_output"):
        z3_details = (
            '<details style="margin-top:0.5rem">'
            '<summary style="cursor:pointer;font-size:0.85rem">z3 output</summary>'
            f'<pre style="font-size:0.78rem;overflow:auto;margin:0.4rem 0 0;'
            f'background:var(--bg-soft);padding:0.5rem;border-radius:4px">'
            f'{escape(result["z3_output"])}</pre></details>'
        )
    return (
        f'<div class="card err" style="margin-bottom:1rem;">'
        f'<strong>&#10007; Spec check failed &mdash; approval blocked</strong>'
        f'<p class="meta" style="margin:0.3rem 0 0">Fix mypy and pytest errors '
        f'before requesting anonymous review.</p>'
        f'{mypy_details}{pytest_details}{z3_details}'
        f'</div>'
    )


def pr_review_page(user_login: str, owner: str, repo: str, pr_num: int,
                   sha: str, pr: dict, files: list,
                   spec_check: dict | None = None) -> str:
    pr_url = pr.get("html_url", f"https://github.com/{owner}/{repo}/pull/{pr_num}")
    title = pr.get("title", "(no title)")
    state = pr.get("state", "open")
    author = pr.get("user", {}).get("login", "?")
    body = pr.get("body") or ""
    additions = pr.get("additions", 0)
    deletions = pr.get("deletions", 0)
    changed = pr.get("changed_files", len(files))
    short_sha = sha[:7]
    pr_slug_field = f"{owner}/{repo}/{pr_num}/{sha}"

    sc = spec_check or {}
    spec_failed = not sc.get("passed", True) and not sc.get("skipped", True)
    approve_blocked = "disabled" if spec_failed else ""

    # ── Spec check sidebar widget ──────────────────────────────────────────
    def _check_row(label: str, ok: bool | None, detail: str = "") -> str:
        if ok is None:
            icon = '<span style="color:var(--fg-muted)">—</span>'
        elif ok:
            icon = '<span style="color:var(--success)">✓</span>'
        else:
            icon = '<span style="color:var(--danger)">✗</span>'
        detail_html = f' <span style="color:var(--fg-muted);font-size:0.78rem">{escape(detail)}</span>' if detail else ""
        return (f'<div style="display:flex;align-items:center;gap:0.5rem;'
                f'padding:0.35rem 0;border-bottom:1px solid var(--border);font-size:0.85rem">'
                f'<span style="width:1.1rem;text-align:center;font-weight:600">{icon}</span>'
                f'<span>{escape(label)}</span>{detail_html}</div>')

    if sc.get("source") == "ci":
        # The verdict came from the reviewed repository's CI. There are no local
        # mypy/pytest/z3 sub-results to show, so report the gate itself and link
        # to the run rather than implying the issuer ran the tools.
        passed = sc.get("passed")
        colour = "var(--success)" if passed else "var(--danger)"
        headline = ("Spec gate passed in CI" if passed
                    else "Spec gate not passed — approval blocked")
        detail = escape(str(sc.get("reason", "")))
        link = sc.get("details_url")
        spec_widget = (
            f'<div style="font-size:0.8rem;font-weight:600;color:{colour};'
            f'margin-bottom:0.4rem">{headline}</div>'
            f'<p class="meta" style="margin:0;font-size:0.78rem">{detail}</p>'
        )
        if link:
            spec_widget += (
                f'<p class="meta" style="margin:0.4rem 0 0;font-size:0.78rem">'
                f'<a href="{escape(link)}" target="_blank" rel="noopener">View the CI run →</a></p>'
            )
        spec_widget += (
            '<p class="meta" style="margin:0.4rem 0 0;font-size:0.74rem">'
            'Checks run in the repository\'s own CI, not in the issuer.</p>'
        )
    elif sc.get("skipped"):
        spec_widget = '<p class="meta" style="margin:0;font-size:0.82rem">No Python files — spec check skipped.</p>'
    else:
        mypy_ok = sc.get("mypy_ok")
        pytest_ok = sc.get("pytest_ok") if sc.get("has_tests") else None
        z3_ok = sc.get("z3_ok") if sc.get("has_z3") else None
        rows = _check_row("mypy", mypy_ok, "" if mypy_ok else "type errors")
        rows += _check_row("pytest", pytest_ok, "no tests" if pytest_ok is None else ("" if pytest_ok else "failures"))
        rows += _check_row("z3 properties", z3_ok, "not present" if z3_ok is None else ("" if z3_ok else "failed"))
        n = sc.get("files_checked", 0)
        status_color = "var(--success)" if sc.get("passed") else "var(--danger)"
        status_text = "All checks passed" if sc.get("passed") else "Check failures — approval blocked"
        spec_widget = f"""
          <div style="font-size:0.8rem;font-weight:600;color:{status_color};
                      margin-bottom:0.4rem">{status_text}</div>
          <div style="border:1px solid var(--border);border-radius:6px;overflow:hidden">{rows}</div>
          <p class="meta" style="margin:0.4rem 0 0;font-size:0.78rem">{n} file(s) checked</p>"""
        if not sc.get("passed") and not sc.get("skipped"):
            errs = []
            if not sc.get("mypy_ok", True) and sc.get("mypy_output"):
                errs.append(('mypy errors', sc["mypy_output"]))
            if not sc.get("pytest_ok", True) and sc.get("pytest_output"):
                errs.append(('pytest output', sc["pytest_output"]))
            if not sc.get("z3_ok", True) and sc.get("z3_output"):
                errs.append(('z3 output', sc["z3_output"]))
            for (lbl, out) in errs:
                spec_widget += (
                    f'<details style="margin-top:0.5rem">'
                    f'<summary style="cursor:pointer;font-size:0.78rem;color:var(--fg-muted)">{lbl}</summary>'
                    f'<pre style="font-size:0.72rem;overflow:auto;margin:0.3rem 0 0;'
                    f'background:var(--bg-soft);padding:0.5rem;border-radius:4px;max-height:180px">'
                    f'{escape(out)}</pre></details>'
                )

    # ── Files ─────────────────────────────────────────────────────────────
    files_html = []
    for f in files:
        fname = f.get("filename", "?")
        status = f.get("status", "modified")
        adds = f.get("additions", 0)
        dels = f.get("deletions", 0)
        patch = f.get("patch", "")
        chevron = ('<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor"'
                   ' stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"'
                   ' class="file-chevron"><polyline points="9 18 15 12 9 6"/></svg>')
        files_html.append(f"""
        <details class="file" {"open" if len(files) <= 3 else ""}>
          <summary>
            {chevron}
            <span class="filename">{escape(fname)}</span>
            {_file_status_badge(status)}
            <span style="margin-left:auto;display:flex;gap:0.4rem;flex-shrink:0">
              <span class="adds">+{adds}</span>
              <span class="dels">&minus;{dels}</span>
            </span>
          </summary>
          {_diff_html(patch)}
        </details>""")
    if not files:
        files_html.append('<p class="meta">No files in this PR.</p>')

    body_html = ('<p style="margin:0;white-space:pre-wrap;color:var(--fg-muted);font-size:0.9rem">'
                 + escape(body[:600]) + ('…' if len(body) > 600 else '') + '</p>') if body else ''

    state_color = "var(--success)" if state == "open" else "var(--fg-muted)"

    return page("Review PR", f"""
      <style>
        /* Escape the global 760px .container constraint for this wide layout */
        .container {{ max-width: 1100px !important; padding-left: 1.5rem; padding-right: 1.5rem; }}
        .review-wrap {{ padding: 2rem 0; }}
        .pr-title-row {{ display:flex; align-items:flex-start; gap:0.75rem; margin-bottom:0.5rem; }}
        .pr-title-row h1 {{ margin:0; font-size:1.4rem; flex:1; line-height:1.3; }}
        .pr-state {{ flex-shrink:0; display:inline-flex; align-items:center; gap:0.35rem;
                     padding:0.25rem 0.65rem; border-radius:2em; font-size:0.78rem;
                     font-weight:600; border:1px solid {state_color}; color:{state_color}; margin-top:3px; }}
        .pr-meta {{ display:flex; flex-wrap:wrap; gap:0.5rem 1rem; font-size:0.85rem;
                    color:var(--fg-muted); margin-bottom:1.5rem; align-items:center; }}
        .pr-meta a {{ color:var(--fg-muted); text-decoration:none; }}
        .pr-meta a:hover {{ color:var(--accent); }}
        .stat-pill {{ display:inline-flex; gap:0.35rem; background:var(--bg-soft);
                      border:1px solid var(--border); border-radius:4px;
                      padding:0.15rem 0.55rem; font-family:ui-monospace,monospace;
                      font-size:0.82rem; }}
        .stat-add {{ color:var(--success); }}
        .stat-del {{ color:var(--danger); }}

        /* two-column layout */
        .review-cols {{ display:grid; grid-template-columns:1fr 280px; gap:1.5rem;
                        align-items:start; }}
        @media(max-width:820px) {{
          .review-cols {{ grid-template-columns:1fr; }}
          .review-sidebar {{ order:-1; }}
        }}
        .review-sidebar {{ position:sticky; top:calc(48px + 1rem); }}
        .sidebar-card {{ background:var(--bg); border:1px solid var(--border);
                         border-radius:8px; padding:1.1rem; margin-bottom:0.85rem;
                         box-shadow:var(--shadow); }}
        .sidebar-card h4 {{ margin:0 0 0.65rem; font-size:0.85rem;
                            text-transform:uppercase; letter-spacing:0.04em;
                            color:var(--fg-muted); }}

        /* file diffs */
        .file {{ border:1px solid var(--border); border-radius:8px; margin:0.6rem 0;
                 background:var(--bg); overflow:hidden; }}
        .file > summary {{ padding:0.6rem 0.9rem; cursor:pointer; list-style:none;
                           background:var(--bg-soft); display:flex; align-items:center;
                           gap:0.5rem; border-bottom:1px solid transparent;
                           font-family:ui-monospace,SFMono-Regular,Menlo,monospace;
                           font-size:0.82rem; }}
        .file[open] > summary {{ border-bottom-color:var(--border); }}
        .file > summary::-webkit-details-marker {{ display:none; }}
        .file-chevron {{ flex-shrink:0; color:var(--fg-muted); transition:transform 0.15s; }}
        .file[open] > summary .file-chevron {{ transform:rotate(90deg); }}
        .file .filename {{ font-weight:600; flex:1; word-break:break-all; }}
        .file .adds {{ color:var(--success); font-weight:600; }}
        .file .dels {{ color:var(--danger); font-weight:600; }}
        .diff {{ margin:0; padding:0; background:var(--bg);
                 font-family:ui-monospace,SFMono-Regular,Menlo,monospace;
                 font-size:0.79rem; line-height:1.5; overflow-x:auto; }}
        .ln {{ display:block; padding:0 1rem; white-space:pre; }}
        .ln.add {{ background:rgba(46,160,67,0.1); color:#2ea043; }}
        .ln.del {{ background:rgba(248,81,73,0.1); color:#f85149; }}
        .ln.hunk {{ background:var(--bg-soft); color:var(--fg-muted);
                    border-top:1px solid var(--border); border-bottom:1px solid var(--border); }}
        @media(prefers-color-scheme:dark) {{
          .ln.add {{ background:rgba(46,160,67,0.15); color:#3fb950; }}
          .ln.del {{ background:rgba(248,81,73,0.15); color:#f85149; }}
        }}

        /* approve button */
        .btn-approve {{ width:100%; padding:0.7rem; font-size:0.95rem; font-weight:600;
                        border-radius:6px; border:none; cursor:pointer;
                        background:var(--success); color:#fff; display:flex;
                        align-items:center; justify-content:center; gap:0.5rem;
                        transition:opacity 0.15s, filter 0.15s; }}
        .btn-approve:hover:not([disabled]) {{ filter:brightness(1.08); }}
        .btn-approve[disabled] {{ opacity:0.45; cursor:not-allowed; }}
        .zk-info {{ font-size:0.78rem; color:var(--fg-muted); line-height:1.5;
                    display:flex; gap:0.4rem; align-items:flex-start; margin-top:0.5rem; }}
        .section-label {{ font-size:0.8rem; font-weight:600; color:var(--fg-muted);
                          text-transform:uppercase; letter-spacing:0.05em;
                          margin:1.25rem 0 0.5rem; }}
        textarea.comment-box {{
          width:100%; padding:0.55rem 0.6rem; border:1px solid var(--border);
          border-radius:6px; background:var(--bg); color:var(--fg);
          font:inherit; font-size:0.85rem; resize:vertical; min-height:72px; }}
        textarea.comment-box:focus {{
          outline:none; border-color:var(--accent);
          box-shadow:0 0 0 3px rgba(9,105,218,0.15); }}
        .confirm-label {{ display:flex; align-items:center; gap:0.5rem;
                          font-size:0.875rem; font-weight:500; cursor:pointer;
                          margin-bottom:0.75rem; }}
        .confirm-label input {{ width:16px; height:16px; accent-color:var(--accent); }}
      </style>

      <div class="review-wrap">
        <div class="review-cols">
          <!-- ── Main content ── -->
          <div class="review-main">
            <div class="pr-title-row">
              <h1>{escape(title)}</h1>
              <span class="pr-state">
                <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                     stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                  <circle cx="18" cy="18" r="3"/><circle cx="6" cy="6" r="3"/>
                  <path d="M13 6h3a2 2 0 0 1 2 2v7"/><line x1="6" y1="9" x2="6" y2="21"/>
                </svg>
                {escape(state)}
              </span>
            </div>
            <div class="pr-meta">
              <a href="{escape(pr_url)}" target="_blank">{escape(owner)}/{escape(repo)} #{pr_num}</a>
              <span>by <strong>@{escape(author)}</strong></span>
              <span class="kbd" style="font-size:0.8rem">{escape(short_sha)}</span>
              <span class="stat-pill">
                <span class="stat-add">+{additions}</span>
                <span class="stat-del">&minus;{deletions}</span>
                <span style="color:var(--fg-muted)">{changed} file(s)</span>
              </span>
            </div>

            {"" if not body_html else f'<div class="card" style="margin-bottom:1rem;padding:1rem 1.25rem">{body_html}</div>'}

            <div class="section-label">Changed files &nbsp;({changed})</div>
            {"".join(files_html)}
          </div>

          <!-- ── Sidebar ── -->
          <div class="review-sidebar">

            <!-- Spec check card -->
            <div class="sidebar-card">
              <h4>Spec verification</h4>
              {spec_widget}
            </div>

            <!-- Approve card -->
            <div class="sidebar-card">
              <h4>Anonymous approval</h4>
              <form id="approve-form" onsubmit="return false">
                <input type="hidden" name="pr_slug" id="pr-slug" value="{escape(pr_slug_field)}">
                <label style="font-size:0.8rem;font-weight:500;display:block;margin-bottom:0.3rem">
                  Comment <span style="color:var(--fg-muted);font-weight:400">(optional, posted via bot)</span>
                </label>
                <textarea class="comment-box" name="comment" rows="3"
                          placeholder="LGTM. Logic looks correct…"></textarea>
                <label class="confirm-label" style="margin-top:0.6rem">
                  <input type="checkbox" id="confirm" required {approve_blocked}>
                  I&rsquo;ve reviewed these changes
                </label>
                <button class="btn-approve" id="submit-btn" type="button" disabled {approve_blocked}>
                  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                       stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
                  </svg>
                  Approve anonymously
                </button>
              </form>
              <div class="zk-info">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                     stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="flex-shrink:0;margin-top:2px">
                  <rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>
                </svg>
                Generates a Longfellow ZK proof in your browser (~5 s). Your device key never
                leaves this machine, so the issuer cannot approve on your behalf.
              </div>
            </div>

          </div><!-- /sidebar -->
        </div><!-- /cols -->
      </div><!-- /wrap -->

      <div class="overlay" id="loading-overlay">
        <div class="panel">
          <div class="spinner"></div>
          <h3>Proving in your browser&hellip;</h3>
          <p class="step-text" id="loading-step">Preparing device key</p>
          <div class="progress-bar"><span id="loading-bar" style="width:4%"></span></div>
          <p class="meta" style="margin-top:0.75rem">
            Bound to <span class="kbd">{escape(short_sha)}</span>.
            Your device key stays on this machine.
          </p>
          <p class="meta" id="loading-error"
             style="margin-top:0.75rem;color:var(--warn);display:none"></p>
        </div>
      </div>

      <script type="module">
        import {{ runApproval }} from '/js/approve.js';

        const cb = document.getElementById('confirm');
        const btn = document.getElementById('submit-btn');
        cb.addEventListener('change', () => {{ btn.disabled = !cb.checked; }});

        const overlay = document.getElementById('loading-overlay');
        const stepEl = document.getElementById('loading-step');
        const bar = document.getElementById('loading-bar');
        const errEl = document.getElementById('loading-error');

        // Progress is reported by the worker at real milestones rather than on a
        // timer, so a stall is visible instead of being papered over.
        const onProgress = (text, pct) => {{
          stepEl.textContent = text;
          if (pct) bar.style.width = pct + '%';
        }};

        btn.addEventListener('click', async () => {{
          if (!cb.checked) return;
          overlay.classList.add('active');
          btn.disabled = true;
          errEl.style.display = 'none';
          try {{
            const res = await runApproval({{
              prSlug: document.getElementById('pr-slug').value,
              comment: document.querySelector('textarea[name=comment]').value,
              onProgress,
            }});
            window.location.href = res.redirect;
          }} catch (e) {{
            stepEl.textContent = 'Approval failed';
            errEl.textContent = e.message || String(e);
            errEl.style.display = 'block';
            btn.disabled = false;
          }}
        }});
      </script>
    """, user=user_login)


def approve_result_page(login: str, pr_key: str, count: int, required: int,
                        passed: bool, proof_hash: str, took_ms: int,
                        comment_url: str | None = None,
                        circuit_id: str | None = None,
                        proof_size_bytes: int | None = None,
                        transcript_hex: str | None = None,
                        prover_ms: int | None = None,
                        issuer_pkx: str | None = None) -> str:
    badge = ('<span class="badge ok">passing</span>' if passed
             else f'<span class="badge err">{count} / {required}</span>')
    card_cls = "card ok" if passed else "card"
    body_msg = ("Merge gate is now <strong>green</strong>."
                if passed else
                f"Need <strong>{required - count}</strong> more anonymous reviewer(s).")
    comment_block = ""
    if comment_url:
        comment_block = f"""
        <div class="card compact" style="margin-top: 0.75rem">
          Your comment was posted anonymously on the PR. The author shown
          is the bot; your identity stayed with the issuer.
          <a href="{escape(comment_url)}" target="_blank" style="margin-left: 0.4rem">View on GitHub &rarr;</a>
        </div>"""

    def _row(label: str, value: str, mono: bool = True) -> str:
        val_html = f'<span class="kbd" style="word-break:break-all">{escape(value)}</span>' if mono else escape(value)
        return f'<tr><td style="color:var(--fg-muted);white-space:nowrap;padding:0.3rem 1rem 0.3rem 0;vertical-align:top;font-size:0.85rem">{escape(label)}</td><td style="font-size:0.85rem;padding:0.3rem 0">{val_html}</td></tr>'

    proof_size_str = "—"
    if proof_size_bytes:
        if proof_size_bytes >= 1_000_000:
            proof_size_str = f"{proof_size_bytes / 1_000_000:.1f} MB"
        else:
            proof_size_str = f"{proof_size_bytes / 1_000:.0f} KB"

    timing_str = f"{took_ms / 1000:.1f} s total"
    if prover_ms:
        verify_ms = took_ms - prover_ms
        timing_str = f"{prover_ms / 1000:.1f} s prove · {verify_ms / 1000:.1f} s verify"

    receipt_rows = [
        _row("Proof hash", proof_hash),
        _row("Circuit ID", circuit_id or "—"),
        _row("Transcript", (transcript_hex or "")[:48] + "…" if transcript_hex else "—"),
        _row("Issuer key", (issuer_pkx or "—")[:18] + "…" if issuer_pkx else "—"),
        _row("Proof size", proof_size_str, mono=False),
        _row("Timing", timing_str, mono=False),
    ]

    receipt_block = f"""
    <div class="card" style="margin-top:1rem">
      <h3 style="margin-top:0;font-size:0.95rem;display:flex;align-items:center;gap:0.5rem">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="flex-shrink:0"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
        ZK Proof Receipt
      </h3>
      <table style="border-collapse:collapse;width:100%">{"".join(receipt_rows)}</table>
      <p class="meta" style="margin:0.75rem 0 0;font-size:0.78rem">
        Proof generated by <a href="https://github.com/google/longfellow-zk" target="_blank">Google Longfellow</a>
        over ISO&nbsp;18013-5 mDL circuit. The verifier checked this proof against the
        issuer's public key and the transcript bound to commit
        <span class="kbd">{escape(pr_key.split("/")[-1][:7])}</span> — your identity was never transmitted.
      </p>
    </div>"""

    return page("Approval submitted", f"""
        <style>
          .receipt-copy {{ cursor:pointer; background:none; border:none; color:var(--fg-muted);
                          font-size:0.75rem; padding:0 0.25rem; vertical-align:middle; }}
          .receipt-copy:hover {{ color:var(--accent); }}
        </style>
        <h1>Approval submitted {badge}</h1>
        <p class="subtitle"><span class="kbd">{escape(pr_key)}</span></p>
        <div class="{card_cls}">
          <p style="margin-top:0">Anonymous ZK proof accepted for this commit.</p>
          <p>Backend reports <strong>{count} / {required}</strong> valid proofs. {body_msg}</p>
        </div>
        {comment_block}
        {receipt_block}
        <p style="margin-top:1.5rem">
          <a class="btn" href="/review">Approve another PR</a>
          &nbsp;
          <a class="btn secondary" href="/synthesize">Synthesize another</a>
        </p>
    """, user=login)


def synthesize_page(login: str, error: str | None = None) -> str:
    err = f'<div class="card err compact">{escape(error)}</div>' if error else ""
    return page("Synthesize AI Code", f"""
        <h1>Synthesize AI code</h1>
        <p class="subtitle">
          Describe what to build. Claude generates the implementation + tests,
          creates a GitHub PR, and verifies it with mypy + pytest before you can approve.
        </p>
        {err}
        <div class="card">
          <form method="post" action="/synthesize" id="synth-form">
            <label for="spec">Specification</label>
            <textarea id="spec" name="spec" rows="7" required
                      placeholder="Write a Python module `rate_limiter.py` that implements a token-bucket rate limiter.&#10;&#10;Requirements:&#10;- Class RateLimiter(capacity: int, refill_rate: float)&#10;- Method .allow() -> bool: returns True if a token is available&#10;- Thread-safe implementation&#10;- Tests must verify burst capacity and steady-state throughput"
                      style="width:100%; padding:0.55rem; border:1px solid var(--border);
                             border-radius:6px; background:var(--bg); color:var(--fg);
                             font:inherit; resize:vertical; min-height:140px;"></textarea>
            <p class="meta">Be specific about class names, method signatures,
               and requirements — the generated code will be type-checked and tested.</p>

            <label for="repo" style="margin-top:0.85rem">Target repository</label>
            <input type="text" id="repo" name="repo"
                   placeholder="https://github.com/owner/repo  or  owner/repo"
                   autocomplete="off" required>
            <p class="meta">Paste the GitHub repo URL or use <span class="kbd">owner/repo</span>.
               The GitHub App must have <span class="kbd">contents:write</span> +
               <span class="kbd">pull_requests:write</span> on this repo.</p>

            <div style="display:flex;gap:0.75rem;margin-top:1rem;align-items:center">
              <button class="btn large" type="submit" id="synth-btn">
                Synthesize &amp; create PR
              </button>
              <a class="btn secondary" href="/review">Cancel</a>
            </div>
          </form>
        </div>

        <h3 style="margin:2rem 0 0.75rem; font-size:1rem;">What happens next</h3>
        <ol class="howitworks">
          <li><span class="step">1</span><span><strong>Claude synthesizes</strong> the implementation and pytest tests from your spec (~5s).</span></li>
          <li><span class="step">2</span><span><strong>A GitHub PR is created</strong> automatically with the generated code.</span></li>
          <li><span class="step">3</span><span><strong>mypy + pytest run</strong> during review — approval is blocked if either fails.</span></li>
          <li><span class="step">4</span><span><strong>ZK-verified reviewers</strong> approve anonymously; the merge gate turns green once enough approve.</span></li>
        </ol>

        <div class="overlay" id="loading-overlay">
          <div class="panel">
            <div class="spinner"></div>
            <h3>Synthesizing code&hellip;</h3>
            <p class="step-text" id="loading-step">Calling Claude API</p>
            <div class="progress-bar"><span id="loading-bar" style="width:5%"></span></div>
            <p class="meta">~10 seconds. Claude writes the code and tests,
               then we create a branch and PR on GitHub.</p>
          </div>
        </div>

        <script>
          const form = document.getElementById('synth-form');
          const overlay = document.getElementById('loading-overlay');
          const step = document.getElementById('loading-step');
          const bar = document.getElementById('loading-bar');
          const btn = document.getElementById('synth-btn');
          const steps = [
            ['Calling Claude API',          15],
            ['Generating implementation',   40],
            ['Generating tests',            65],
            ['Creating GitHub branch',      80],
            ['Opening pull request',        95],
          ];
          form.addEventListener('submit', () => {{
            overlay.classList.add('active');
            btn.disabled = true;
            let i = 0;
            const tick = () => {{
              if (i < steps.length) {{
                step.textContent = steps[i][0];
                bar.style.width = steps[i][1] + '%';
                i++;
                setTimeout(tick, 1800);
              }}
            }};
            tick();
          }});
        </script>
    """, user=login)
