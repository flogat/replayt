"""Self-contained HTML report template for ``replayt report`` (no external CDN)."""

from __future__ import annotations

import html
import json
from collections import defaultdict, deque
from datetime import datetime
from itertools import zip_longest
from typing import Any, Literal

REPORT_CSS = """
:root {{
  --slate-50: #f8fafc; --slate-100: #f1f5f9; --slate-200: #e2e8f0; --slate-300: #cbd5e1;
  --slate-400: #94a3b8; --slate-500: #64748b; --slate-600: #475569; --slate-700: #334155;
  --slate-800: #1e293b; --slate-900: #0f172a;
  --green-100: #dcfce7; --green-500: #22c55e; --green-800: #166534;
  --red-100: #fee2e2; --red-500: #ef4444; --red-800: #991b1b;
  --yellow-100: #fef9c3; --yellow-800: #854d0e;
}}
body.rp-body {{ margin:0; min-height:100vh; background:var(--slate-50); color:var(--slate-900);
  font-family:ui-sans-serif,system-ui,sans-serif; -webkit-font-smoothing:antialiased; }}
.rp-main {{ max-width:56rem; margin:0 auto; padding:2.5rem 1rem; }}
.rp-section {{ margin-bottom:2rem; }}
.rp-h1 {{ font-size:1.5rem; font-weight:700; letter-spacing:-0.025em; margin:0 0 0.5rem; }}
.rp-h2 {{ font-size:1.125rem; font-weight:600; margin:0 0 0.75rem; }}
.rp-card {{ background:#fff; border:1px solid var(--slate-200); border-radius:0.5rem;
  box-shadow:0 1px 2px rgba(15,23,42,0.06); padding:1.25rem; }}
.rp-card-tight p {{ margin:0.15rem 0; font-size:0.875rem; }}
.rp-label {{ font-weight:500; color:var(--slate-500); }}
.rp-code {{ font-family:ui-monospace,monospace; color:var(--slate-800); font-size:0.9em; }}
.rp-badge {{
  display:inline-block; padding:0.125rem 0.5rem; border-radius:0.25rem; font-size:0.75rem; font-weight:600;
}}
.rp-badge-ok {{ background:var(--green-100); color:var(--green-800); }}
.rp-badge-err {{ background:var(--red-100); color:var(--red-800); }}
.rp-badge-pause {{ background:var(--yellow-100); color:var(--yellow-800); }}
.rp-badge-neutral {{ background:var(--slate-100); color:var(--slate-800); }}
.rp-timeline {{ list-style:none; margin:0; padding:0 0 0 0.75rem; border-left:2px solid var(--slate-300); }}
.rp-tl-item {{ position:relative; margin-bottom:1rem; margin-left:0.5rem; }}
.rp-tl-dot {{ position:absolute; left:-1.15rem; top:0.2rem; width:0.65rem; height:0.65rem;
  border-radius:9999px; border:2px solid #fff; }}
.rp-dot-muted {{ background:var(--slate-400); }}
.rp-dot-ok {{ background:var(--green-500); }}
.rp-dot-err {{ background:var(--red-500); }}
.rp-tl-state {{ font-size:0.875rem; font-weight:500; color:var(--slate-700); margin:0; }}
.rp-tl-ts {{ font-size:0.75rem; color:var(--slate-400); margin:0.15rem 0 0; }}
.rp-muted {{ color:var(--slate-400); font-size:0.875rem; }}
.rp-stack {{ display:flex; flex-direction:column; gap:0.75rem; }}
details.rp-details summary {{
  cursor:pointer; font-size:0.875rem; font-weight:500; color:var(--slate-700); list-style:none;
}}
details.rp-details summary::-webkit-details-marker {{ display:none; }}
details.rp-details summary:hover {{ color:var(--slate-900); }}
.rp-pre {{ margin-top:0.5rem; padding:0.75rem; background:var(--slate-50); border-radius:0.375rem;
  font-size:0.75rem; color:var(--slate-600); border:1px solid var(--slate-100);
  white-space:pre-wrap; word-break:break-all; }}
.rp-divide > * + * {{ border-top:1px solid var(--slate-100); }}
.rp-tc-item {{ padding:1rem; }}
.rp-table {{ width:100%; text-align:left; font-size:0.875rem; border-collapse:collapse; }}
.rp-table th, .rp-table td {{ padding:0.25rem 0; }}
.rp-table th {{ font-weight:500; color:var(--slate-500); }}
.rp-table .rp-num {{ text-align:right; font-family:ui-monospace,monospace; }}
.rp-table thead tr {{ border-bottom:1px solid var(--slate-200); }}
.rp-table tbody tr.rp-total {{ border-top:1px solid var(--slate-200); font-weight:600; }}
.rp-foot {{ font-size:0.75rem; color:var(--slate-400); margin-top:3rem; }}
.rp-seq {{ font-size:0.75rem; color:var(--slate-400); font-weight:400; }}
.rp-kv p {{ margin:0.2rem 0; }}
.rp-note {{ margin-top:0.6rem; font-size:0.8rem; color:var(--slate-500); }}
.rp-callout {{ border-left:4px solid var(--slate-300); }}
.rp-callout-ok {{ border-left-color:var(--green-500); background:var(--green-100); }}
.rp-callout-err {{ border-left-color:var(--red-500); background:var(--red-100); }}
.rp-callout-pause {{ border-left-color:var(--yellow-800); background:var(--yellow-100); }}
"""

REPORT_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>replayt report &mdash; {run_id}</title>
  <style>
""" + REPORT_CSS + """
  </style>
</head>
<body class="rp-body">
  <main class="rp-main">

    <section class="rp-section">
      <h1 class="rp-h1">{report_title}</h1>
      <div class="rp-card rp-card-tight">
        <p><span class="rp-label">Run ID:</span> <code class="rp-code">{run_id}</code></p>
        <p><span class="rp-label">Workflow:</span> {workflow_name}@{workflow_version}</p>
        <p><span class="rp-label">Status:</span>
          <span class="rp-badge {status_class}">{status}</span></p>
        <p><span class="rp-label">Duration:</span> {duration}</p>
        {tags_html}
        {meta_html}
      </div>
    </section>

    {attention_section}

    {approvals_section}

    <section class="rp-section">
      <h2 class="rp-h2">State Timeline</h2>
      <div class="rp-card">
        <ol class="rp-timeline">
          {timeline_html}
        </ol>
      </div>
    </section>

    {outputs_section}

    {tool_calls_section}

    {notes_section}

    {token_section}

    <footer class="rp-foot">Generated by replayt</footer>
  </main>
</body>
</html>
"""

TIMELINE_ITEM = """\
<li class="rp-tl-item">
  <span class="rp-tl-dot {dot_class}"></span>
  <p class="rp-tl-state">{state}</p>
  <p class="rp-tl-ts">{ts}</p>
</li>"""

OUTPUTS_SECTION = """\
    <section class="rp-section">
      <h2 class="rp-h2">Structured Outputs</h2>
      <div class="rp-card rp-stack">
        {items}
      </div>
    </section>"""

OUTPUT_ITEM = """\
<details class="rp-details group">
  <summary>{schema_name}</summary>
  <pre class="rp-pre">{data_json}</pre>
</details>"""

TOOL_CALLS_SECTION = """\
    <section class="rp-section">
      <h2 class="rp-h2">Tool Calls</h2>
      <div class="rp-card rp-divide">
        {items}
      </div>
    </section>"""

TOOL_CALL_ITEM = """\
<details class="rp-details rp-tc-item">
  <summary>{tool} <span class="rp-seq">(seq {seq})</span></summary>
  <pre class="rp-pre">{detail_json}</pre>
</details>"""

NOTES_SECTION = """\
    <section class="rp-section">
      <h2 class="rp-h2">Step Notes</h2>
      <div class="rp-card rp-stack">
        {items}
      </div>
    </section>"""

NOTE_ITEM = """\
<details class="rp-details group">
  <summary>{kind} <span class="rp-seq">(state {state}, seq {seq})</span></summary>
  {summary_block}
  {data_block}
</details>"""

TOKEN_USAGE_SECTION = """\
    <section class="rp-section">
      <h2 class="rp-h2">Token Usage</h2>
      <div class="rp-card rp-card-tight">
        <table class="rp-table">
          <thead><tr>
            <th>Metric</th><th class="rp-num">Value</th>
          </tr></thead>
          <tbody>
            <tr><td>Prompt tokens</td><td class="rp-num">{prompt_tokens}</td></tr>
            <tr><td>Completion tokens</td><td class="rp-num">{completion_tokens}</td></tr>
            <tr class="rp-total"><td>Total tokens</td><td class="rp-num">{total_tokens}</td></tr>
          </tbody>
        </table>
      </div>
    </section>"""

APPROVALS_SECTION = """\
    <section class="rp-section">
      <h2 class="rp-h2">Approvals</h2>
      <div class="rp-card rp-stack">
        {items}
      </div>
    </section>"""

APPROVAL_ITEM = """\
<div class="rp-card rp-card-tight" style="border:1px solid var(--slate-200);">
  <p><span class="rp-label">Approval ID:</span> <code class="rp-code">{approval_id}</code></p>
  <p><span class="rp-label">State:</span> {state}</p>
  <p><span class="rp-label">Summary:</span> {summary}</p>
  {details_block}
  {timing_block}
  {resolution_block}
  {route_block}
  <p><span class="rp-label">Outcome:</span> <strong>{outcome}</strong></p>
</div>"""

ATTENTION_SECTION = """\
    <section class="rp-section">
      <h2 class="rp-h2">{title}</h2>
      <div class="rp-stack">
        {items}
      </div>
    </section>"""

ATTENTION_ITEM = """\
<div class="rp-card rp-card-tight rp-callout {callout_class}">
  <p><strong>{heading}</strong></p>
  {body}
</div>"""


def _legacy_aggregate_run_report_data(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Single pass over events for HTML reports and diff context (rich approval metadata)."""

    workflow_name = ""
    workflow_version = ""
    status = "unknown"
    tags: dict[str, str] = {}
    run_metadata: dict[str, Any] = {}
    states: list[dict[str, str]] = []
    outputs: list[dict[str, Any]] = []
    tool_calls: list[dict[str, Any]] = []
    prompt_tokens = 0
    completion_tokens = 0
    total_tokens = 0
    first_ts: str | None = None
    last_ts: str | None = None
    approvals: list[dict[str, Any]] = []
    pending_approvals: dict[str, deque[int]] = defaultdict(deque)

    for e in events:
        ts = e.get("ts", "")
        if first_ts is None:
            first_ts = ts
        last_ts = ts
        typ = e.get("type")
        payload = e.get("payload") or {}

        if typ == "run_started":
            workflow_name = str(payload.get("workflow_name", ""))
            workflow_version = str(payload.get("workflow_version", ""))
            raw_tags = payload.get("tags") or {}
            tags = raw_tags if isinstance(raw_tags, dict) else {}
            raw_meta = payload.get("run_metadata") or {}
            run_metadata = raw_meta if isinstance(raw_meta, dict) else {}
        elif typ == "state_entered":
            states.append({"state": str(payload.get("state", "")), "ts": ts})
        elif typ == "structured_output":
            outputs.append({"schema_name": payload.get("schema_name", ""), "data": payload.get("data")})
        elif typ == "tool_call":
            tool_calls.append({
                "tool": payload.get("name", ""), "seq": e.get("seq", ""), "args": payload.get("arguments"),
            })
        elif typ == "tool_result":
            tool_calls.append({
                "tool": payload.get("name", "result"),
                "seq": e.get("seq", ""),
                "args": payload.get("result"),
            })
        elif typ == "llm_response":
            usage = payload.get("usage") or {}
            pt = usage.get("prompt_tokens")
            ct = usage.get("completion_tokens")
            tt = usage.get("total_tokens")
            if isinstance(pt, int):
                prompt_tokens += pt
            if isinstance(ct, int):
                completion_tokens += ct
            if isinstance(tt, int):
                total_tokens += tt
        elif typ == "run_completed":
            status = str(payload.get("status", status))
        elif typ == "run_paused":
            status = "paused"
        elif typ == "run_failed":
            status = "failed"
        elif typ == "approval_requested":
            aid = payload.get("approval_id")
            if aid is not None:
                aid_str = str(aid)
                approvals.append(
                    {
                        "approval_id": aid_str,
                        "summary": payload.get("summary", ""),
                        "state": payload.get("state", ""),
                        "details": payload.get("details") or {},
                        "requested_ts": ts,
                        "approved": None,
                        "resolved_ts": None,
                        "orphan_resolution": False,
                    }
                )
                pending_approvals[aid_str].append(len(approvals) - 1)
        elif typ == "approval_resolved":
            aid = payload.get("approval_id")
            if aid is not None:
                aid_str = str(aid)
                approved = bool(payload.get("approved"))
                if pending_approvals[aid_str]:
                    idx = pending_approvals[aid_str].popleft()
                    approvals[idx]["approved"] = approved
                    approvals[idx]["resolved_ts"] = ts
                else:
                    approvals.append(
                        {
                            "approval_id": aid_str,
                            "summary": "",
                            "state": "",
                            "details": {},
                            "requested_ts": None,
                            "approved": approved,
                            "resolved_ts": ts,
                            "orphan_resolution": True,
                        }
                    )

    return {
        "workflow_name": workflow_name,
        "workflow_version": workflow_version,
        "status": status,
        "tags": tags,
        "run_metadata": run_metadata,
        "states": states,
        "outputs": outputs,
        "tool_calls": tool_calls,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "first_ts": first_ts,
        "last_ts": last_ts,
        "approvals": approvals,
    }


def _legacy_collect_report_context(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Parse events into the same shape ``cmd_report`` uses (for single-run and diff reports)."""

    agg = aggregate_run_report_data(events)
    return {
        "workflow_name": agg["workflow_name"],
        "workflow_version": agg["workflow_version"],
        "status": agg["status"],
        "tags": agg["tags"],
        "run_metadata": agg["run_metadata"],
        "states": agg["states"],
        "outputs": agg["outputs"],
        "tool_calls": agg["tool_calls"],
        "prompt_tokens": agg["prompt_tokens"],
        "completion_tokens": agg["completion_tokens"],
        "total_tokens": agg["total_tokens"],
        "first_ts": agg["first_ts"],
        "last_ts": agg["last_ts"],
        "approvals": agg["approvals"],
    }


def _output_occurrence_label(item: dict[str, Any] | None, index: int) -> str:
    schema_name = ""
    if isinstance(item, dict):
        schema_name = str(item.get("schema_name", "")).strip()
    base = schema_name or "output"
    return f"{base} #{index}"


def _approval_occurrence_label(item: dict[str, Any] | None, index: int) -> str:
    approval_id = ""
    if isinstance(item, dict):
        approval_id = str(item.get("approval_id", "")).strip()
    base = approval_id or "approval"
    return f"{base} #{index}"


def _outputs_signature(outputs: list[dict[str, Any]]) -> dict[str, Any]:
    return {str(output.get("schema_name", "")): output.get("data") for output in outputs}


def _json_preview(value: Any, *, limit: int = 4000) -> str:
    raw = json.dumps(value, indent=2, ensure_ascii=False, default=str)
    preview = html.escape(raw[:limit])
    if len(raw) > limit:
        preview += "..."
    return preview


def _preview_block(label: str, value: Any) -> str:
    return (
        f'<p><span class="rp-label">{html.escape(label)}:</span></p>'
        f'<pre class="rp-pre">{_json_preview(value)}</pre>'
    )


def _context_diff_rows(label: str, left: Any, right: Any) -> str:
    same = left == right
    cls = "rp-diff-row" if same else "rp-diff-row rp-changed"
    if same:
        return f'<p class="{cls}"><span class="rp-label">{html.escape(label)}:</span> match</p>'
    return (
        f'<p class="{cls}"><span class="rp-label">{html.escape(label)}:</span> different</p>'
        f'<pre class="rp-pre">A: {html.escape(json.dumps(left, indent=2, default=str)[:1200])}\n\n'
        f'B: {html.escape(json.dumps(right, indent=2, default=str)[:1200])}</pre>'
    )


REPORT_DIFF_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>replayt report diff</title>
  <style>
""" + REPORT_CSS + """
.rp-grid {{ display:grid; grid-template-columns:1fr 1fr; gap:1rem; }}
@media (max-width:48rem) {{ .rp-grid {{ grid-template-columns:1fr; }} }}
.rp-diff-row {{ font-size:0.875rem; margin:0.25rem 0; }}
.rp-changed {{ color:var(--red-800); font-weight:600; }}
  </style>
</head>
<body class="rp-body">
  <main class="rp-main">
    <section class="rp-section">
      <h1 class="rp-h1">Run comparison</h1>
      <p class="rp-muted">Side-by-side summary from recorded JSONL (no model calls).</p>
    </section>
    <section class="rp-section rp-grid">
      <div class="rp-card rp-card-tight">
        <h2 class="rp-h2">Run A</h2>
        <p><span class="rp-label">ID:</span> <code class="rp-code">{run_a}</code></p>
        <p><span class="rp-label">Workflow:</span> {wa_name}@{wa_ver}</p>
        <p><span class="rp-label">Status:</span> {wa_status}</p>
        <p><span class="rp-label">States:</span> {wa_states}</p>
      </div>
      <div class="rp-card rp-card-tight">
        <h2 class="rp-h2">Run B</h2>
        <p><span class="rp-label">ID:</span> <code class="rp-code">{run_b}</code></p>
        <p><span class="rp-label">Workflow:</span> {wb_name}@{wb_ver}</p>
        <p><span class="rp-label">Status:</span> {wb_status}</p>
        <p><span class="rp-label">States:</span> {wb_states}</p>
      </div>
    </section>
    <section class="rp-section">
      <h2 class="rp-h2">Run context</h2>
      <div class="rp-card rp-card-tight">
        {context_diff_rows}
      </div>
    </section>
    <section class="rp-section">
      <h2 class="rp-h2">Failure and pause signals</h2>
      <div class="rp-card rp-card-tight">
        {failure_diff_rows}
      </div>
    </section>
    <section class="rp-section">
      <h2 class="rp-h2">Structured outputs</h2>
      <div class="rp-card">
        {outputs_diff_rows}
      </div>
    </section>
    <section class="rp-section">
      <h2 class="rp-h2">Approvals</h2>
      <div class="rp-card rp-card-tight">
        {approvals_diff}
      </div>
    </section>
    <footer class="rp-foot">Generated by replayt</footer>
  </main>
</body>
</html>"""


def _legacy_build_report_diff_html(
    run_a: str,
    run_b: str,
    ctx_a: dict[str, Any],
    ctx_b: dict[str, Any],
) -> str:
    def state_chain(states: list[dict[str, str]]) -> str:
        return " → ".join(s["state"] for s in states) if states else "(none)"

    sa = _outputs_signature(ctx_a["outputs"])
    sb = _outputs_signature(ctx_b["outputs"])
    keys = sorted(set(sa) | set(sb))
    rows: list[str] = []
    for k in keys:
        va, vb = sa.get(k), sb.get(k)
        same = va == vb
        cls = "rp-diff-row" if same else "rp-diff-row rp-changed"
        rows.append(
            f'<p class="{cls}"><span class="rp-label">{html.escape(k)}:</span> '
            f"{'match' if same else 'different'}</p>"
            + (
                ""
                if same
                else f'<pre class="rp-pre">A: {html.escape(json.dumps(va, indent=2, default=str)[:1200])}\n\n'
                f'B: {html.escape(json.dumps(vb, indent=2, default=str)[:1200])}</pre>'
            )
        )
    if not rows:
        rows.append('<p class="rp-muted">No structured_output events in either run.</p>')

    ar, br = ctx_a["approval_requests"], ctx_b["approval_requests"]
    appr = "A approvals: " + str(len(ar)) + " — B approvals: " + str(len(br))
    if ar != br:
        appr += " (counts or ids differ — open single-run reports for detail)"

    return REPORT_DIFF_HTML.format(
        run_a=html.escape(run_a),
        run_b=html.escape(run_b),
        wa_name=html.escape(str(ctx_a["workflow_name"])),
        wa_ver=html.escape(str(ctx_a["workflow_version"])),
        wa_status=html.escape(str(ctx_a["status"])),
        wa_states=html.escape(state_chain(ctx_a["states"])),
        wb_name=html.escape(str(ctx_b["workflow_name"])),
        wb_ver=html.escape(str(ctx_b["workflow_version"])),
        wb_status=html.escape(str(ctx_b["status"])),
        wb_states=html.escape(state_chain(ctx_b["states"])),
        outputs_diff_rows="\n".join(rows),
        approvals_diff=html.escape(appr),
    )


def _parse_iso_ts(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        s = str(ts)
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _legacy_build_run_report_html(
    run_id: str,
    events: list[dict[str, Any]],
    *,
    style: Literal["default", "stakeholder"] = "default",
) -> str:
    """Build the same self-contained HTML as ``replayt report`` (for CLI and bundle export)."""

    agg = aggregate_run_report_data(events)
    workflow_name = agg["workflow_name"]
    workflow_version = agg["workflow_version"]
    status = agg["status"]
    tags = agg["tags"]
    run_metadata = agg["run_metadata"]
    states = agg["states"]
    outputs = agg["outputs"]
    tool_calls = agg["tool_calls"]
    prompt_tokens = agg["prompt_tokens"]
    completion_tokens = agg["completion_tokens"]
    total_tokens = agg["total_tokens"]
    first_ts = agg["first_ts"]
    last_ts = agg["last_ts"]
    approval_requests = agg["approval_requests"]
    approval_last = agg["approval_last"]
    approval_resolved_ts = agg["approval_resolved_ts"]

    duration = "n/a"
    t0 = _parse_iso_ts(first_ts)
    t1 = _parse_iso_ts(last_ts)
    if t0 and t1:
        delta = t1 - t0
        secs = delta.total_seconds()
        if secs < 60:
            duration = f"{secs:.1f}s"
        else:
            duration = f"{secs / 60:.1f}m"

    status_classes = {
        "completed": "rp-badge-ok",
        "failed": "rp-badge-err",
        "paused": "rp-badge-pause",
    }
    status_class = status_classes.get(status, "rp-badge-neutral")

    tags_html = ""
    if tags:
        tag_strs = ", ".join(f"{html.escape(k)}={html.escape(v)}" for k, v in tags.items())
        tags_html = f'<p><span class="rp-label">Tags:</span> {tag_strs}</p>'
    meta_html = ""
    if run_metadata:
        meta_html = (
            '<p><span class="rp-label">Run metadata:</span> '
            f'<code class="rp-code">{html.escape(json.dumps(run_metadata, default=str)[:4000])}</code></p>'
        )

    timeline_items: list[str] = []
    for s in states:
        dot_class = "rp-dot-muted"
        if s["state"] == states[-1]["state"] and status == "completed":
            dot_class = "rp-dot-ok"
        elif s["state"] == states[-1]["state"] and status == "failed":
            dot_class = "rp-dot-err"
        timeline_items.append(
            TIMELINE_ITEM.format(state=html.escape(s["state"]), ts=html.escape(s["ts"]), dot_class=dot_class)
        )
    timeline_html = (
        "\n".join(timeline_items)
        if timeline_items
        else '<li class="rp-tl-item"><p class="rp-muted">No states recorded</p></li>'
    )

    outputs_section = ""
    if outputs:
        items = []
        for o in outputs:
            items.append(
                OUTPUT_ITEM.format(
                    schema_name=html.escape(str(o["schema_name"])),
                    data_json=html.escape(json.dumps(o["data"], indent=2, default=str)),
                )
            )
        outputs_section = OUTPUTS_SECTION.format(items="\n".join(items))

    tool_calls_section = ""
    if tool_calls and style == "default":
        items = []
        for tc in tool_calls:
            items.append(
                TOOL_CALL_ITEM.format(
                    tool=html.escape(str(tc["tool"])),
                    seq=html.escape(str(tc["seq"])),
                    detail_json=html.escape(json.dumps(tc.get("args"), indent=2, default=str)),
                )
            )
        tool_calls_section = TOOL_CALLS_SECTION.format(items="\n".join(items))

    approvals_section = ""
    if approval_requests:
        items_a: list[str] = []
        for aid, meta in sorted(approval_requests.items()):
            if aid in approval_last:
                outcome = "Approved" if approval_last[aid] else "Rejected"
            else:
                outcome = "Pending (no resolution in this log)"
            details = meta.get("details") or {}
            if isinstance(details, dict) and details:
                raw_d = json.dumps(details, ensure_ascii=False, default=str)
                prev = html.escape(raw_d[:4000])
                if len(raw_d) > 4000:
                    prev += "…"
                details_block = f'<p><span class="rp-label">Details:</span></p><pre class="rp-pre">{prev}</pre>'
            else:
                details_block = ""
            rt = str(meta.get("requested_ts") or "")
            vt = approval_resolved_ts.get(aid, "")
            if rt or vt:
                timing_block = (
                    "<p><span class=\"rp-label\">Timeline:</span> "
                    f"requested <code class=\"rp-code\">{html.escape(rt or '—')}</code>"
                    " → "
                    f"resolved <code class=\"rp-code\">{html.escape(vt or '—')}</code></p>"
                )
            else:
                timing_block = ""
            items_a.append(
                APPROVAL_ITEM.format(
                    approval_id=html.escape(aid),
                    state=html.escape(str(meta.get("state", ""))),
                    summary=html.escape(str(meta.get("summary", ""))),
                    details_block=details_block,
                    timing_block=timing_block,
                    outcome=html.escape(outcome),
                )
            )
        appr_block = APPROVALS_SECTION.format(items="\n".join(items_a))
        if style == "stakeholder":
            intro = (
                '<p class="rp-muted">Human approval gates from the JSONL timeline '
                "(stakeholder view; tool/token sections omitted below).</p>\n"
            )
            approvals_section = intro + appr_block
        else:
            approvals_section = appr_block

    if style == "stakeholder":
        token_section = (
            '<section class="rp-section"><p class="rp-muted">Tool-call and token usage sections omitted. '
            "For the full technical report, run "
            f'<code class="rp-code">replayt report {html.escape(run_id)} --style default</code>'
            "</p></section>"
        )
        report_title = "Run summary"
    else:
        token_section = TOKEN_USAGE_SECTION.format(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        )
        report_title = "Run Report"

    return REPORT_HTML.format(
        report_title=html.escape(report_title),
        run_id=html.escape(run_id),
        workflow_name=html.escape(workflow_name),
        workflow_version=html.escape(workflow_version),
        status=html.escape(status),
        status_class=status_class,
        duration=html.escape(duration),
        tags_html=tags_html,
        meta_html=meta_html,
        approvals_section=approvals_section,
        timeline_html=timeline_html,
        outputs_section=outputs_section,
        tool_calls_section=tool_calls_section,
        notes_section="",
        token_section=token_section,
    )


def aggregate_run_report_data(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Single pass over events for HTML reports and diff context (rich approval metadata)."""

    workflow_name = ""
    workflow_version = ""
    status = "unknown"
    tags: dict[str, str] = {}
    run_metadata: dict[str, Any] = {}
    experiment: dict[str, Any] = {}
    workflow_meta: dict[str, Any] = {}
    states: list[dict[str, str]] = []
    outputs: list[dict[str, Any]] = []
    tool_calls: list[dict[str, Any]] = []
    notes: list[dict[str, Any]] = []
    approvals: list[dict[str, Any]] = []
    pending_approvals: dict[str, deque[int]] = defaultdict(deque)
    resolved_approvals: deque[int] = deque()
    failure: dict[str, Any] | None = None
    structured_output_failures: list[dict[str, Any]] = []
    retry_count = 0
    latest_retry: dict[str, Any] | None = None
    prompt_tokens = 0
    completion_tokens = 0
    total_tokens = 0
    first_ts: str | None = None
    last_ts: str | None = None

    for event in events:
        ts = str(event.get("ts", ""))
        if first_ts is None:
            first_ts = ts
        last_ts = ts
        typ = event.get("type")
        payload = event.get("payload") or {}

        if typ == "run_started":
            workflow_name = str(payload.get("workflow_name", ""))
            workflow_version = str(payload.get("workflow_version", ""))
            raw_tags = payload.get("tags") or {}
            tags = raw_tags if isinstance(raw_tags, dict) else {}
            raw_meta = payload.get("run_metadata") or {}
            run_metadata = raw_meta if isinstance(raw_meta, dict) else {}
            raw_experiment = payload.get("experiment") or {}
            experiment = raw_experiment if isinstance(raw_experiment, dict) else {}
            raw_workflow_meta = payload.get("workflow_meta") or {}
            workflow_meta = raw_workflow_meta if isinstance(raw_workflow_meta, dict) else {}
        elif typ == "state_entered":
            states.append({"state": str(payload.get("state", "")), "ts": ts})
        elif typ == "structured_output":
            outputs.append({"schema_name": payload.get("schema_name", ""), "data": payload.get("data")})
        elif typ == "structured_output_failed":
            structured_output_failures.append(
                {
                    "state": payload.get("state"),
                    "schema_name": payload.get("schema_name"),
                    "stage": payload.get("stage"),
                    "structured_output_mode": payload.get("structured_output_mode"),
                    "error": payload.get("error"),
                    "response_chars": payload.get("response_chars"),
                    "ts": ts,
                }
            )
        elif typ == "tool_call":
            tool_calls.append(
                {"tool": payload.get("name", ""), "seq": event.get("seq", ""), "args": payload.get("arguments")}
            )
        elif typ == "tool_result":
            tool_calls.append(
                {
                    "tool": payload.get("name", "result"),
                    "seq": event.get("seq", ""),
                    "args": payload.get("result"),
                }
            )
        elif typ == "step_note":
            notes.append(
                {
                    "seq": event.get("seq", ""),
                    "ts": ts,
                    "state": payload.get("state"),
                    "kind": payload.get("kind"),
                    "summary": payload.get("summary"),
                    "data": payload.get("data"),
                }
            )
        elif typ == "llm_response":
            usage = payload.get("usage") or {}
            pt = usage.get("prompt_tokens")
            ct = usage.get("completion_tokens")
            tt = usage.get("total_tokens")
            if isinstance(pt, int):
                prompt_tokens += pt
            if isinstance(ct, int):
                completion_tokens += ct
            if isinstance(tt, int):
                total_tokens += tt
        elif typ == "retry_scheduled":
            retry_count += 1
            latest_retry = {
                "state": payload.get("state"),
                "attempt": payload.get("attempt"),
                "max_attempts": payload.get("max_attempts"),
                "error": payload.get("error"),
                "ts": ts,
            }
        elif typ == "run_completed":
            status = str(payload.get("status", status))
        elif typ == "run_paused":
            status = "paused"
        elif typ == "run_failed":
            status = "failed"
            failure = {
                "state": payload.get("state"),
                "error": payload.get("error"),
                "ts": ts,
            }
        elif typ == "approval_requested":
            aid = payload.get("approval_id")
            if aid is not None:
                aid_str = str(aid)
                approvals.append(
                    {
                        "approval_id": aid_str,
                        "summary": payload.get("summary", ""),
                        "state": payload.get("state", ""),
                        "details": payload.get("details") or {},
                        "on_approve": payload.get("on_approve"),
                        "on_reject": payload.get("on_reject"),
                        "requested_ts": ts,
                        "approved": None,
                        "resolved_ts": None,
                        "resolver": None,
                        "reason": None,
                        "actor": None,
                        "approval_state": None,
                        "resumed_at_state": None,
                        "orphan_resolution": False,
                    }
                )
                pending_approvals[aid_str].append(len(approvals) - 1)
        elif typ == "approval_resolved":
            aid = payload.get("approval_id")
            if aid is not None:
                aid_str = str(aid)
                approved = bool(payload.get("approved"))
                if pending_approvals[aid_str]:
                    idx = pending_approvals[aid_str].popleft()
                    approvals[idx]["approved"] = approved
                    approvals[idx]["resolved_ts"] = ts
                    approvals[idx]["resolver"] = payload.get("resolver")
                    approvals[idx]["reason"] = payload.get("reason")
                    approvals[idx]["actor"] = payload.get("actor")
                    resolved_approvals.append(idx)
                else:
                    approvals.append(
                        {
                            "approval_id": aid_str,
                            "summary": "",
                            "state": "",
                            "details": {},
                            "on_approve": None,
                            "on_reject": None,
                            "requested_ts": None,
                            "approved": approved,
                            "resolved_ts": ts,
                            "resolver": payload.get("resolver"),
                            "reason": payload.get("reason"),
                            "actor": payload.get("actor"),
                            "approval_state": None,
                            "resumed_at_state": None,
                            "orphan_resolution": True,
                        }
                    )
                    resolved_approvals.append(len(approvals) - 1)
        elif typ == "approval_applied" and resolved_approvals:
            idx = resolved_approvals.popleft()
            approvals[idx]["approval_state"] = payload.get("approval_state")
            approvals[idx]["resumed_at_state"] = payload.get("resumed_at_state")

    return {
        "workflow_name": workflow_name,
        "workflow_version": workflow_version,
        "status": status,
        "tags": tags,
        "run_metadata": run_metadata,
        "experiment": experiment,
        "workflow_meta": workflow_meta,
        "states": states,
        "outputs": outputs,
        "tool_calls": tool_calls,
        "notes": notes,
        "failure": failure,
        "structured_output_failures": structured_output_failures,
        "retry_count": retry_count,
        "latest_retry": latest_retry,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "first_ts": first_ts,
        "last_ts": last_ts,
        "approvals": approvals,
    }


def collect_report_context(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Parse events into the same shape ``cmd_report`` uses (for single-run and diff reports)."""

    agg = aggregate_run_report_data(events)
    return {
        "workflow_name": agg["workflow_name"],
        "workflow_version": agg["workflow_version"],
        "status": agg["status"],
        "tags": agg["tags"],
        "run_metadata": agg["run_metadata"],
        "experiment": agg["experiment"],
        "workflow_meta": agg["workflow_meta"],
        "states": agg["states"],
        "outputs": agg["outputs"],
        "tool_calls": agg["tool_calls"],
        "notes": agg["notes"],
        "failure": agg["failure"],
        "structured_output_failures": agg["structured_output_failures"],
        "retry_count": agg["retry_count"],
        "latest_retry": agg["latest_retry"],
        "prompt_tokens": agg["prompt_tokens"],
        "completion_tokens": agg["completion_tokens"],
        "total_tokens": agg["total_tokens"],
        "first_ts": agg["first_ts"],
        "last_ts": agg["last_ts"],
        "approvals": agg["approvals"],
    }


def build_report_diff_html(
    run_a: str,
    run_b: str,
    ctx_a: dict[str, Any],
    ctx_b: dict[str, Any],
) -> str:
    def state_chain(states: list[dict[str, str]]) -> str:
        return " -> ".join(s["state"] for s in states) if states else "(none)"

    context_rows = [
        _context_diff_rows("Tags", ctx_a["tags"], ctx_b["tags"]),
        _context_diff_rows("Run metadata", ctx_a["run_metadata"], ctx_b["run_metadata"]),
        _context_diff_rows("Experiment", ctx_a["experiment"], ctx_b["experiment"]),
        _context_diff_rows("Workflow metadata", ctx_a["workflow_meta"], ctx_b["workflow_meta"]),
    ]

    latest_parse_a = ctx_a["structured_output_failures"][-1] if ctx_a["structured_output_failures"] else None
    latest_parse_b = ctx_b["structured_output_failures"][-1] if ctx_b["structured_output_failures"] else None
    failure_rows = [
        _context_diff_rows("Run failure", ctx_a["failure"], ctx_b["failure"]),
        _context_diff_rows("Latest structured parse failure", latest_parse_a, latest_parse_b),
        _context_diff_rows("Retries scheduled", ctx_a["retry_count"], ctx_b["retry_count"]),
    ]

    output_rows: list[str] = []
    for idx, (left, right) in enumerate(zip_longest(ctx_a["outputs"], ctx_b["outputs"], fillvalue=None), start=1):
        label = _output_occurrence_label(left if left is not None else right, idx)
        same = left == right
        cls = "rp-diff-row" if same else "rp-diff-row rp-changed"
        output_rows.append(
            f'<p class="{cls}"><span class="rp-label">{html.escape(label)}:</span> '
            f"{'match' if same else 'different'}</p>"
            + (
                ""
                if same
                else f'<pre class="rp-pre">A: {html.escape(json.dumps(left, indent=2, default=str)[:1200])}\n\n'
                f'B: {html.escape(json.dumps(right, indent=2, default=str)[:1200])}</pre>'
            )
        )
    if not output_rows:
        output_rows.append('<p class="rp-muted">No structured_output events in either run.</p>')

    approval_rows: list[str] = []
    for idx, (left, right) in enumerate(
        zip_longest(ctx_a["approvals"], ctx_b["approvals"], fillvalue=None),
        start=1,
    ):
        label = _approval_occurrence_label(left if left is not None else right, idx)
        same = left == right
        cls = "rp-diff-row" if same else "rp-diff-row rp-changed"
        approval_rows.append(
            f'<p class="{cls}"><span class="rp-label">{html.escape(label)}:</span> '
            f"{'match' if same else 'different'}</p>"
            + (
                ""
                if same
                else f'<pre class="rp-pre">A: {html.escape(json.dumps(left, indent=2, default=str)[:1200])}\n\n'
                f'B: {html.escape(json.dumps(right, indent=2, default=str)[:1200])}</pre>'
            )
        )
    approvals_html = (
        "\n".join(approval_rows) if approval_rows else '<p class="rp-muted">No approvals in either run.</p>'
    )

    return REPORT_DIFF_HTML.format(
        run_a=html.escape(run_a),
        run_b=html.escape(run_b),
        wa_name=html.escape(str(ctx_a["workflow_name"])),
        wa_ver=html.escape(str(ctx_a["workflow_version"])),
        wa_status=html.escape(str(ctx_a["status"])),
        wa_states=html.escape(state_chain(ctx_a["states"])),
        wb_name=html.escape(str(ctx_b["workflow_name"])),
        wb_ver=html.escape(str(ctx_b["workflow_version"])),
        wb_status=html.escape(str(ctx_b["status"])),
        wb_states=html.escape(state_chain(ctx_b["states"])),
        context_diff_rows="\n".join(context_rows),
        failure_diff_rows="\n".join(failure_rows),
        outputs_diff_rows="\n".join(output_rows),
        approvals_diff=approvals_html,
    )


def build_run_report_html(
    run_id: str,
    events: list[dict[str, Any]],
    *,
    style: Literal["default", "stakeholder", "support"] = "default",
) -> str:
    """Build the same self-contained HTML as ``replayt report`` (for CLI and bundle export)."""

    agg = aggregate_run_report_data(events)
    workflow_name = agg["workflow_name"]
    workflow_version = agg["workflow_version"]
    status = agg["status"]
    tags = agg["tags"]
    run_metadata = agg["run_metadata"]
    experiment = agg["experiment"]
    workflow_meta = agg["workflow_meta"]
    states = agg["states"]
    outputs = agg["outputs"]
    tool_calls = agg["tool_calls"]
    notes = agg["notes"]
    failure = agg["failure"]
    structured_output_failures = agg["structured_output_failures"]
    retry_count = agg["retry_count"]
    latest_retry = agg["latest_retry"]
    prompt_tokens = agg["prompt_tokens"]
    completion_tokens = agg["completion_tokens"]
    total_tokens = agg["total_tokens"]
    first_ts = agg["first_ts"]
    last_ts = agg["last_ts"]
    approvals = agg["approvals"]

    duration = "n/a"
    t0 = _parse_iso_ts(first_ts)
    t1 = _parse_iso_ts(last_ts)
    if t0 and t1:
        delta = t1 - t0
        secs = delta.total_seconds()
        if secs < 60:
            duration = f"{secs:.1f}s"
        else:
            duration = f"{secs / 60:.1f}m"

    status_classes = {
        "completed": "rp-badge-ok",
        "failed": "rp-badge-err",
        "paused": "rp-badge-pause",
    }
    status_class = status_classes.get(status, "rp-badge-neutral")

    tags_html = ""
    if tags:
        tag_strs = ", ".join(f"{html.escape(k)}={html.escape(v)}" for k, v in tags.items())
        tags_html = f'<p><span class="rp-label">Tags:</span> {tag_strs}</p>'
    meta_parts: list[str] = []
    if run_metadata:
        meta_parts.append(
            '<p><span class="rp-label">Run metadata:</span> '
            f'<code class="rp-code">{html.escape(json.dumps(run_metadata, default=str)[:4000])}</code></p>'
        )
    if experiment:
        meta_parts.append(
            '<p><span class="rp-label">Experiment:</span> '
            f'<code class="rp-code">{html.escape(json.dumps(experiment, default=str)[:4000])}</code></p>'
        )
    if workflow_meta:
        meta_parts.append(
            '<p><span class="rp-label">Workflow metadata:</span> '
            f'<code class="rp-code">{html.escape(json.dumps(workflow_meta, default=str)[:4000])}</code></p>'
        )
    meta_html = "\n".join(meta_parts)

    pending_approvals = [approval for approval in approvals if approval.get("approved") is None]
    attention_items: list[str] = []
    if status == "failed" and failure:
        err = failure.get("error") or {}
        body = [
            f'<p><span class="rp-label">State:</span> {html.escape(str(failure.get("state") or "-"))}</p>',
            f'<p><span class="rp-label">Error:</span> {html.escape(str(err.get("type") or "Error"))}: '
            f'{html.escape(str(err.get("message") or ""))}</p>',
        ]
        attention_items.append(
            ATTENTION_ITEM.format(
                callout_class="rp-callout-err",
                heading="Run failed",
                body="".join(body),
            )
        )
    elif status == "paused":
        pending_ids = ", ".join(
            html.escape(str(approval.get("approval_id") or "")) for approval in pending_approvals
        ) or "-"
        body = [
            f'<p><span class="rp-label">Pending approvals:</span> {len(pending_approvals)}</p>',
            f'<p><span class="rp-label">Approval IDs:</span> {pending_ids}</p>',
        ]
        attention_items.append(
            ATTENTION_ITEM.format(
                callout_class="rp-callout-pause",
                heading="Run is waiting for approval",
                body="".join(body),
            )
        )

    if structured_output_failures:
        parse_failure = structured_output_failures[-1]
        parse_error = parse_failure.get("error") or {}
        body = [
            f'<p><span class="rp-label">Schema:</span> {html.escape(str(parse_failure.get("schema_name") or "-"))}</p>',
            f'<p><span class="rp-label">Stage:</span> {html.escape(str(parse_failure.get("stage") or "-"))}</p>',
            f'<p><span class="rp-label">State:</span> {html.escape(str(parse_failure.get("state") or "-"))}</p>',
            f'<p><span class="rp-label">Error:</span> {html.escape(str(parse_error.get("message") or ""))}</p>',
        ]
        attention_items.append(
            ATTENTION_ITEM.format(
                callout_class="rp-callout-err",
                heading="Latest structured parse failure",
                body="".join(body),
            )
        )

    if retry_count:
        body = [f'<p><span class="rp-label">Retries scheduled:</span> {retry_count}</p>']
        if latest_retry:
            retry_error = latest_retry.get("error") or {}
            body.append(
                f'<p><span class="rp-label">Latest retry:</span> state '
                f'{html.escape(str(latest_retry.get("state") or "-"))}, '
                f'attempt {html.escape(str(latest_retry.get("attempt") or "-"))}/'
                f'{html.escape(str(latest_retry.get("max_attempts") or "-"))}</p>'
            )
            if isinstance(retry_error, dict) and retry_error.get("message"):
                body.append(
                    f'<p><span class="rp-label">Retry error:</span> '
                    f'{html.escape(str(retry_error.get("message") or ""))}</p>'
                )
        attention_items.append(
            ATTENTION_ITEM.format(
                callout_class="rp-callout-pause",
                heading="Retries happened during this run",
                body="".join(body),
            )
        )
    attention_section = ""
    if attention_items:
        attention_title = "Support summary" if style == "support" else "Action summary"
        attention_section = ATTENTION_SECTION.format(title=attention_title, items="\n".join(attention_items))

    timeline_items: list[str] = []
    for state_meta in states:
        dot_class = "rp-dot-muted"
        if state_meta["state"] == states[-1]["state"] and status == "completed":
            dot_class = "rp-dot-ok"
        elif state_meta["state"] == states[-1]["state"] and status == "failed":
            dot_class = "rp-dot-err"
        timeline_items.append(
            TIMELINE_ITEM.format(
                state=html.escape(state_meta["state"]),
                ts=html.escape(state_meta["ts"]),
                dot_class=dot_class,
            )
        )
    timeline_html = (
        "\n".join(timeline_items)
        if timeline_items
        else '<li class="rp-tl-item"><p class="rp-muted">No states recorded</p></li>'
    )

    outputs_section = ""
    if outputs:
        items = []
        for output in outputs:
            items.append(
                OUTPUT_ITEM.format(
                    schema_name=html.escape(str(output["schema_name"])),
                    data_json=html.escape(json.dumps(output["data"], indent=2, default=str)),
                )
            )
        outputs_section = OUTPUTS_SECTION.format(items="\n".join(items))

    tool_calls_section = ""
    if tool_calls and style == "default":
        items = []
        for tool_call in tool_calls:
            items.append(
                TOOL_CALL_ITEM.format(
                    tool=html.escape(str(tool_call["tool"])),
                    seq=html.escape(str(tool_call["seq"])),
                    detail_json=html.escape(json.dumps(tool_call.get("args"), indent=2, default=str)),
                )
            )
        tool_calls_section = TOOL_CALLS_SECTION.format(items="\n".join(items))

    notes_section = ""
    if notes:
        items = []
        for note in notes:
            summary_block = ""
            if note.get("summary") not in (None, ""):
                summary_block = (
                    f'<p class="rp-note"><span class="rp-label">Summary:</span> '
                    f'{html.escape(str(note.get("summary") or ""))}</p>'
                )
            data_block = ""
            if note.get("data") not in (None, "", {}):
                data_block = f'<pre class="rp-pre">{_json_preview(note.get("data"))}</pre>'
            items.append(
                NOTE_ITEM.format(
                    kind=html.escape(str(note.get("kind") or "")),
                    state=html.escape(str(note.get("state") or "")),
                    seq=html.escape(str(note.get("seq") or "")),
                    summary_block=summary_block,
                    data_block=data_block,
                )
            )
        notes_section = NOTES_SECTION.format(items="\n".join(items))

    approvals_section = ""
    if approvals:
        items_a: list[str] = []
        for approval in approvals:
            approved = approval.get("approved")
            if approved is True:
                outcome = "Approved"
            elif approved is False:
                outcome = "Rejected"
            else:
                outcome = "Pending (no resolution in this log)"
            if approval.get("orphan_resolution"):
                outcome += " [missing approval_requested event]"
            details = approval.get("details") or {}
            if isinstance(details, dict) and details:
                raw_details = json.dumps(details, ensure_ascii=False, default=str)
                preview = html.escape(raw_details[:4000])
                if len(raw_details) > 4000:
                    preview += "..."
                details_block = (
                    f'<p><span class="rp-label">Details:</span></p><pre class="rp-pre">{preview}</pre>'
                )
            else:
                details_block = ""
            requested_ts = str(approval.get("requested_ts") or "")
            resolved_ts = str(approval.get("resolved_ts") or "")
            if requested_ts or resolved_ts:
                timing_block = (
                    "<p><span class=\"rp-label\">Timeline:</span> "
                    f"requested <code class=\"rp-code\">{html.escape(requested_ts or '-')}</code>"
                    " -> "
                    f"resolved <code class=\"rp-code\">{html.escape(resolved_ts or '-')}</code></p>"
                )
            else:
                timing_block = ""
            resolution_lines: list[str] = []
            if approval.get("resolver"):
                resolution_lines.append(
                    f'<p><span class="rp-label">Resolver:</span> '
                    f'{html.escape(str(approval.get("resolver") or ""))}</p>'
                )
            if approval.get("reason"):
                resolution_lines.append(
                    f'<p><span class="rp-label">Reason:</span> '
                    f'{html.escape(str(approval.get("reason") or ""))}</p>'
                )
            actor = approval.get("actor")
            if actor not in (None, "", {}):
                resolution_lines.append(_preview_block("Actor", actor))
            resolution_block = "".join(resolution_lines)

            route_lines: list[str] = []
            if approval.get("approval_state") or approval.get("resumed_at_state"):
                route_lines.append(
                    "<p><span class=\"rp-label\">Resume path:</span> "
                    f'{html.escape(str(approval.get("approval_state") or "-"))} -> '
                    f'{html.escape(str(approval.get("resumed_at_state") or "-"))}</p>'
                )
            elif approval.get("approved") is True and approval.get("on_approve"):
                route_lines.append(
                    f'<p><span class="rp-label">Configured on approve:</span> '
                    f'{html.escape(str(approval.get("on_approve") or ""))}</p>'
                )
            elif approval.get("approved") is False and approval.get("on_reject"):
                route_lines.append(
                    f'<p><span class="rp-label">Configured on reject:</span> '
                    f'{html.escape(str(approval.get("on_reject") or ""))}</p>'
                )
            elif approval.get("approved") is None and (approval.get("on_approve") or approval.get("on_reject")):
                route_lines.append(
                    f'<p><span class="rp-label">Configured approve path:</span> '
                    f'{html.escape(str(approval.get("on_approve") or "-"))}</p>'
                )
                route_lines.append(
                    f'<p><span class="rp-label">Configured reject path:</span> '
                    f'{html.escape(str(approval.get("on_reject") or "-"))}</p>'
                )
            route_block = "".join(route_lines)
            items_a.append(
                APPROVAL_ITEM.format(
                    approval_id=html.escape(str(approval.get("approval_id", ""))),
                    state=html.escape(str(approval.get("state", ""))),
                    summary=html.escape(str(approval.get("summary", ""))),
                    details_block=details_block,
                    timing_block=timing_block,
                    resolution_block=resolution_block,
                    route_block=route_block,
                    outcome=html.escape(outcome),
                )
            )
        appr_block = APPROVALS_SECTION.format(items="\n".join(items_a))
        if style in {"stakeholder", "support"}:
            intro = (
                '<p class="rp-muted">Human approval gates from the JSONL timeline '
                "(stakeholder-facing view; tool/token sections omitted below).</p>\n"
            )
            approvals_section = intro + appr_block
        else:
            approvals_section = appr_block

    if style in {"stakeholder", "support"}:
        token_section = (
            '<section class="rp-section"><p class="rp-muted">Tool-call and token usage sections omitted. '
            "For the full technical report, run "
            f'<code class="rp-code">replayt report {html.escape(run_id)} --style default</code>'
            "</p></section>"
        )
        report_title = "Support handoff" if style == "support" else "Run summary"
    else:
        token_section = TOKEN_USAGE_SECTION.format(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        )
        report_title = "Run Report"

    return REPORT_HTML.format(
        report_title=html.escape(report_title),
        run_id=html.escape(run_id),
        workflow_name=html.escape(workflow_name),
        workflow_version=html.escape(workflow_version),
        status=html.escape(status),
        status_class=status_class,
        duration=html.escape(duration),
        tags_html=tags_html,
        meta_html=meta_html,
        attention_section=attention_section,
        approvals_section=approvals_section,
        timeline_html=timeline_html,
        outputs_section=outputs_section,
        tool_calls_section=tool_calls_section,
        notes_section=notes_section,
        token_section=token_section,
    )
