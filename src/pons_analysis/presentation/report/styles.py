"""Embedded stylesheet for the standalone report."""

STYLES = """\
:root {
  color-scheme: light dark;
  --bg: #f8fafc; --fg: #0f172a; --muted: #64748b; --border: #cbd5e1;
  --surface: #ffffff; --accent: #2563eb; --curve: #d97706; --v4: #2563eb;
  --success: #15803d; --error: #b91c1c; --warning: #b45309;
}
@media (prefers-color-scheme: dark) {
  :root { --bg: #0b1120; --fg: #e2e8f0; --muted: #94a3b8; --border: #334155;
           --surface: #111827; --accent: #60a5fa; --curve: #fbbf24; --v4: #60a5fa;
           --success: #4ade80; --error: #f87171; --warning: #fbbf24; }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--fg);
  font: 15px/1.55 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width: 1100px; margin: 0 auto; padding: 28px 20px 60px; }
header { margin-bottom: 20px; }
h1 { font-size: 26px; margin: 0 0 6px; letter-spacing: -0.01em; }
h2 { font-size: 18px; margin: 0 0 14px; }
h3 { font-size: 14px; margin: 18px 0 8px; color: var(--muted);
  text-transform: uppercase; letter-spacing: 0.04em; }
.muted { color: var(--muted); }
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
  gap: 12px; margin: 18px 0; }
.card { background: var(--surface); border: 1px solid var(--border);
  border-radius: 12px; padding: 14px 16px; }
.card .k { color: var(--muted); font-size: 11px; text-transform: uppercase;
  letter-spacing: 0.05em; }
.card .v { font-size: 21px; margin-top: 4px; font-variant-numeric: tabular-nums; }
section { background: var(--surface); border: 1px solid var(--border);
  border-radius: 14px; padding: 20px; margin: 18px 0; }
.table-wrap { width: 100%; overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-variant-numeric: tabular-nums; }
th, td { padding: 7px 9px; border-bottom: 1px solid var(--border);
  text-align: left; white-space: nowrap; }
th { color: var(--muted); font-size: 11px; text-transform: uppercase;
  letter-spacing: 0.04em; font-weight: 600; }
td.num, th.num { text-align: right; }
tr:last-child td { border-bottom: 0; }
.badge { display: inline-block; padding: 3px 9px; border-radius: 999px;
  font-size: 12px; font-weight: 600; margin-right: 6px; }
.badge.ok { color: var(--success); background: rgba(21, 128, 61, 0.12); }
.badge.bad { color: var(--error); background: rgba(185, 28, 28, 0.12); }
.badge.muted { color: var(--muted); background: rgba(100, 116, 139, 0.12); }
.chart { width: 100%; height: auto; display: block; margin-top: 8px; }
.toc { position: sticky; top: 0; z-index: 2; display: flex; flex-wrap: wrap;
  gap: 6px 14px; margin: 8px 0 4px; padding: 10px 0 12px;
  border-bottom: 1px solid var(--border); background: var(--bg); }
.toc a { color: var(--accent); text-decoration: none; font-size: 13px; }
.toc a:hover { text-decoration: underline; }
.back { display: inline-block; margin-top: 12px; color: var(--muted);
  font-size: 12px; text-decoration: none; }
section { scroll-margin-top: 96px; }
@media (max-width: 900px) {
  .toc { position: static; }
  section { scroll-margin-top: 0; }
}
@media print {
  .toc, .back { display: none; }
  body { background: #fff; color: #000; }
  main { max-width: none; padding: 0; }
  section { break-inside: avoid; page-break-inside: avoid; }
  .table-wrap { overflow: visible; }
  thead { display: table-header-group; }
  .card, .badge { print-color-adjust: exact; }
}
.grid { stroke: var(--border); stroke-width: 1; }
.axis { fill: var(--muted); font-size: 11px; }
.legend { font-size: 11px; fill: var(--muted); }
.legend.curve { fill: var(--curve); }
.legend.v4 { fill: var(--v4); }
.volume { fill: var(--border); opacity: 0.55; }
.candle-up { fill: var(--success); stroke: var(--success); }
.candle-down { fill: var(--error); stroke: var(--error); }
.wick { stroke-width: 1.2; }
code { font-size: 12px; }
footer { color: var(--muted); text-align: center; padding: 24px; }"""
