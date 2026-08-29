"""
UI theme and small rendering helpers for app.py -- kept separate from the
Streamlit page code so the visual system (colors, cards, badges) is defined
once and reused consistently across every tab.

Color discipline (per the dataviz method): decorative choices (the hero
banner gradient, medal accents on the leaderboard) are free picks -- they
don't encode data. Anything that DOES encode data (evidence-quality status,
per-supplier chart colors, criteria weight shares) uses the validated
reference palette's status/categorical/sequential slots unchanged, so hue
differences are actually colorblind-safe rather than just "looking fine."
"""
import hashlib

# --- Validated data-encoding colors (from the dataviz skill's reference palette) ---
CATEGORICAL = [
    "#2a78d6",  # 1 blue
    "#eb6834",  # 2 orange
    "#1baf7a",  # 3 aqua
    "#eda100",  # 4 yellow
    "#e87ba4",  # 5 magenta
    "#008300",  # 6 green
    "#4a3aa7",  # 7 violet
    "#e34948",  # 8 red
]

STATUS = {
    "good": "#0ca30c",
    "warning": "#fab219",
    "serious": "#ec835a",
    "critical": "#d03b3b",
}

# evidence_status -> status role (ordinal: strong is best, missing is worst)
EVIDENCE_STATUS_MAP = {
    "strong": ("good", "✓", "Strong evidence"),
    "moderate": ("warning", "●", "Moderate evidence"),
    "weak": ("serious", "▲", "Weak evidence"),
    "missing": ("critical", "✕", "Missing evidence"),
}

SEQUENTIAL_BLUE = "#2a78d6"

# --- Decorative-only choices (not data encoding -- free to pick) ---
GRADIENT_CSS = "linear-gradient(135deg, #4338CA 0%, #6D28D9 55%, #9333EA 100%)"
MEDAL_ACCENTS = {1: "#D4AF37", 2: "#9CA3AF", 3: "#B87333"}  # gold / silver / bronze


def supplier_color(index: int) -> str:
    """Stable color per supplier by insertion order (identity, not rank) --
    re-ranking a supplier must never repaint its color."""
    return CATEGORICAL[index % len(CATEGORICAL)]


def initials(name: str) -> str:
    parts = [p for p in name.replace("&", " ").split() if p]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


def stable_color_for(key: str) -> str:
    h = int(hashlib.md5(key.encode()).hexdigest(), 16)
    return CATEGORICAL[h % len(CATEGORICAL)]


def inject_css():
    return """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

html, body, [class*="css"] { font-family: 'Inter', system-ui, -apple-system, sans-serif; }

:root {
  --brand-1: #4338CA;
  --brand-2: #9333EA;
  --surface: #ffffff;
  --page: #f9f9f7;
  --ink: #0b0b0b;
  --ink-secondary: #52514e;
  --ink-muted: #898781;
  --border: rgba(11,11,11,0.08);
  --gridline: #e1e0d9;
  --good: #0ca30c;
  --warning: #fab219;
  --serious: #ec835a;
  --critical: #d03b3b;
}

.block-container { padding-top: 1.2rem; max-width: 1200px; }

/* ---------- Hero banner ---------- */
.hero-banner {
  background: linear-gradient(135deg, #4338CA 0%, #6D28D9 55%, #9333EA 100%);
  border-radius: 18px;
  padding: 2.1rem 2.4rem;
  margin-bottom: 1.4rem;
  box-shadow: 0 10px 30px -12px rgba(79,70,229,0.45);
  position: relative;
  overflow: hidden;
}
.hero-banner::after {
  content: "";
  position: absolute; top: -40%; right: -10%;
  width: 320px; height: 320px; border-radius: 50%;
  background: radial-gradient(circle, rgba(255,255,255,0.14) 0%, rgba(255,255,255,0) 70%);
}
.hero-eyebrow {
  color: rgba(255,255,255,0.85); font-size: 0.78rem; font-weight: 700;
  letter-spacing: 0.10em; text-transform: uppercase; margin-bottom: 0.4rem;
}
.hero-title {
  color: #ffffff; font-size: 2.0rem; font-weight: 800; margin: 0 0 0.35rem 0;
  letter-spacing: -0.02em;
}
.hero-subtitle {
  color: rgba(255,255,255,0.92); font-size: 1.0rem; font-weight: 400; max-width: 640px;
  margin-bottom: 1.1rem; line-height: 1.5;
}
.pipeline-row { display: flex; flex-wrap: wrap; gap: 0.5rem; position: relative; z-index: 1; }
.pipeline-badge {
  background: rgba(255,255,255,0.16); border: 1px solid rgba(255,255,255,0.28);
  color: #ffffff; padding: 0.30rem 0.75rem; border-radius: 999px;
  font-size: 0.80rem; font-weight: 600; backdrop-filter: blur(4px);
  display: inline-flex; align-items: center; gap: 0.4rem;
}
.pipeline-arrow { color: rgba(255,255,255,0.55); font-size: 0.85rem; align-self: center; }

/* ---------- Generic cards ---------- */
.card {
  background: var(--surface); border: 1px solid var(--border); border-radius: 14px;
  padding: 1.1rem 1.3rem; margin-bottom: 0.8rem;
  box-shadow: 0 1px 2px rgba(11,11,11,0.03);
}
.card:hover { border-color: rgba(79,70,229,0.25); }

/* ---------- Status badges (evidence quality) ---------- */
.status-badge {
  display: inline-flex; align-items: center; gap: 0.35rem;
  padding: 0.18rem 0.65rem; border-radius: 999px; font-size: 0.76rem; font-weight: 700;
  color: #ffffff; white-space: nowrap;
}

/* ---------- Progress / weight bars ---------- */
.bar-track { background: var(--gridline); border-radius: 999px; height: 8px; overflow: hidden; }
.bar-fill { height: 100%; border-radius: 999px; }

/* ---------- Metric tiles ---------- */
.metric-tile {
  background: var(--surface); border: 1px solid var(--border); border-radius: 12px;
  padding: 0.85rem 1rem; text-align: left;
}
.metric-label { color: var(--ink-muted); font-size: 0.72rem; font-weight: 700;
  text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 0.2rem;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  text-align: left !important; text-justify: auto; word-spacing: normal; }
.metric-value { color: var(--ink); font-size: 1.5rem; font-weight: 800; line-height: 1.1; }
.metric-sub { color: var(--ink-secondary); font-size: 0.82rem; margin-top: 0.15rem; }

/* ---------- Avatars ---------- */
.avatar {
  width: 38px; height: 38px; border-radius: 10px; display: inline-flex;
  align-items: center; justify-content: center; color: #fff; font-weight: 700;
  font-size: 0.85rem; flex-shrink: 0;
}

/* ---------- Rank rows ---------- */
.rank-row {
  display: flex; align-items: center; gap: 0.9rem;
  background: var(--surface); border: 1px solid var(--border); border-radius: 14px;
  padding: 0.9rem 1.2rem; margin-bottom: 0.6rem; border-left-width: 5px; border-left-style: solid;
}
.rank-number { font-size: 1.3rem; font-weight: 800; color: var(--ink-muted); width: 2rem; text-align: center; }

/* ---------- Tabs ---------- */
button[data-baseweb="tab"] {
  font-weight: 600 !important; font-size: 0.95rem !important; padding: 0.6rem 1.1rem !important;
}
button[data-baseweb="tab"][aria-selected="true"] {
  color: #4338CA !important;
}
div[data-baseweb="tab-highlight"] { background: linear-gradient(90deg, #4338CA, #9333EA) !important; height: 3px !important; }

/* ---------- Buttons ---------- */
.stButton > button[kind="primary"] {
  background: linear-gradient(135deg, #4338CA, #9333EA); border: none;
  font-weight: 700; box-shadow: 0 4px 14px -4px rgba(79,70,229,0.55);
}
.stButton > button[kind="primary"]:hover { opacity: 0.92; }

/* ---------- Sidebar ---------- */
[data-testid="stSidebar"] { background: #ffffff; border-right: 1px solid var(--border); }

/* ---------- Evidence quote block ---------- */
.evidence-quote {
  border-left: 3px solid var(--gridline); padding: 0.4rem 0.8rem; margin: 0.4rem 0;
  font-size: 0.85rem; color: var(--ink-secondary); font-style: italic; border-radius: 0 8px 8px 0;
  background: var(--page);
}
.evidence-quote.verified { border-left-color: var(--good); }
.evidence-quote.unverified { border-left-color: var(--critical); background: #fdf2f2; }

/* ---------- Scoring detail table ---------- */
.scoring-table-wrap {
  background: var(--surface); border: 1px solid var(--border); border-radius: 14px;
  padding: 0.3rem 0.2rem 0.5rem; margin: 0.3rem 0 0.6rem; overflow-x: auto;
}
table.scoring-table { width: 100%; border-collapse: collapse; font-size: 0.86rem; }
table.scoring-table thead th {
  text-align: left; color: var(--ink-muted); font-size: 0.68rem; font-weight: 700;
  text-transform: uppercase; letter-spacing: 0.05em; padding: 0.6rem 0.9rem;
  border-bottom: 1px solid var(--gridline); white-space: nowrap;
}
table.scoring-table thead th.num, table.scoring-table td.num { text-align: right; }
table.scoring-table tbody td {
  padding: 0.6rem 0.9rem; border-bottom: 1px solid var(--gridline);
  color: var(--ink); vertical-align: middle;
}
table.scoring-table tbody tr:last-child td { border-bottom: none; }
table.scoring-table tbody tr:hover td { background: var(--page); }
.score-cell { display: flex; align-items: center; gap: 0.6rem; }
.score-cell .bar-track { flex: 1; min-width: 64px; }
.score-cell .score-num { font-variant-numeric: tabular-nums; font-weight: 700; width: 1.6rem; text-align: right; }
.crit-name { font-weight: 600; color: var(--ink); }
.crit-weight { color: var(--ink-muted); font-size: 0.78rem; margin-left: 0.3rem; }
.gap-pos { color: var(--good); font-weight: 700; font-variant-numeric: tabular-nums; }
.gap-zero { color: var(--ink-secondary); font-variant-numeric: tabular-nums; }
.gap-neg { color: var(--critical); font-weight: 700; font-variant-numeric: tabular-nums; }
.deterministic-badge {
  display: inline-flex; align-items: center; gap: 0.35rem; padding: 0.16rem 0.65rem;
  border-radius: 999px; font-size: 0.74rem; font-weight: 700; color: var(--ink-secondary);
  background: var(--page); border: 1px solid var(--border); white-space: nowrap;
}
</style>
"""


def hero_banner(title: str, subtitle: str, stages: list):
    stage_html = ""
    for i, stage in enumerate(stages):
        if i > 0:
            stage_html += '<span class="pipeline-arrow">&#8594;</span>'
        stage_html += f'<span class="pipeline-badge">{stage}</span>'
    return f"""
<div class="hero-banner">
  <div class="hero-eyebrow">Agentic AI &middot; Procurement Intelligence</div>
  <div class="hero-title">{title}</div>
  <div class="hero-subtitle">{subtitle}</div>
  <div class="pipeline-row">{stage_html}</div>
</div>
"""


def status_badge(evidence_status: str) -> str:
    role, icon, label = EVIDENCE_STATUS_MAP.get(evidence_status, ("warning", "?", evidence_status))
    color = STATUS[role]
    return f'<span class="status-badge" style="background:{color}">{icon} {label}</span>'


def bar(value: float, max_value: float, color: str = SEQUENTIAL_BLUE, height: int = 8) -> str:
    pct = 0 if max_value <= 0 else max(0, min(100, (value / max_value) * 100))
    return (f'<div class="bar-track" style="height:{height}px">'
            f'<div class="bar-fill" style="width:{pct}%; background:{color}; height:{height}px"></div></div>')


def metric_tile(label: str, value: str, sub: str = "") -> str:
    sub_html = f'<div class="metric-sub">{sub}</div>' if sub else ""
    return (f'<div class="metric-tile"><div class="metric-label">{label}</div>'
            f'<div class="metric-value">{value}</div>{sub_html}</div>')


def avatar(name: str, color: str) -> str:
    return f'<span class="avatar" style="background:{color}">{initials(name)}</span>'


def _gap_cell(gap) -> str:
    if gap is None:
        return '<span class="gap-zero">&mdash;</span>'
    if gap > 0:
        return f'<span class="gap-pos">+{gap:g}</span>'
    if gap < 0:
        return f'<span class="gap-neg">{gap:g}</span>'
    return '<span class="gap-zero">+0</span>'


def scoring_table(rows: list) -> str:
    """Renders the per-criterion scoring breakdown as a styled HTML table, not
    a native st.dataframe -- st.dataframe is a canvas-based grid widget that
    can't take this app's CSS, so it always looks like generic Streamlit
    chrome next to the rest of the hand-styled UI. This gives full control
    (brand-colored progress bars, colored gap indicators, evidence badges)
    at the cost of native sort/resize, which a ~5-8 row table doesn't need.

    Each row dict: name, weight, score, max_score, contribution, benchmark,
    gap, relative_pct, evidence_status (None for a deterministic criterion).
    """
    body = ""
    for r in rows:
        score_bar = bar(r["score"], r["max_score"], color=SEQUENTIAL_BLUE)
        benchmark = r.get("benchmark")
        benchmark_html = f"{benchmark:g}" if benchmark is not None else "&mdash;"
        rel = r.get("relative_pct")
        rel_html = f"{rel:.1f}%" if rel is not None else "&mdash;"
        evidence_html = (status_badge(r["evidence_status"]) if r.get("evidence_status")
                          else '<span class="deterministic-badge">&#9670; Deterministic</span>')
        body += f"""
        <tr>
          <td><span class="crit-name">{r['name']}</span><span class="crit-weight">({r['weight']:g}%)</span></td>
          <td><div class="score-cell">{score_bar}<span class="score-num">{r['score']:g}</span></div></td>
          <td class="num">{r['contribution']:.2f}</td>
          <td class="num">{benchmark_html}</td>
          <td class="num">{_gap_cell(r.get('gap'))}</td>
          <td class="num">{rel_html}</td>
          <td>{evidence_html}</td>
        </tr>"""
    return f"""
<div class="scoring-table-wrap">
<table class="scoring-table">
<thead><tr>
  <th>Criterion</th><th>Score</th><th class="num">Contribution</th>
  <th class="num">Peer Benchmark</th><th class="num">Gap</th><th class="num">Relative %</th><th>Evidence</th>
</tr></thead>
<tbody>{body}</tbody>
</table>
</div>
"""
