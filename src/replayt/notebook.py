from __future__ import annotations

import html
import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from replayt.persistence.base import EventStore
    from replayt.workflow import Workflow

try:
    from IPython.display import HTML as _IPyHTML
    from IPython.display import display as _ipython_display

    _HAS_IPYTHON = True
except ImportError:
    _HAS_IPYTHON = False
    _IPyHTML = None  # type: ignore[assignment,misc]
    _ipython_display = None  # type: ignore[assignment]


def _m_id(state: str) -> str:
    safe = "".join(ch if ch.isalnum() else "_" for ch in state)
    return f"s_{safe}"


def _build_mermaid_source(wf: Workflow) -> str:
    lines = ["graph TD"]
    for name in wf.step_names():
        label = name.replace('"', "#quot;")
        nid = _m_id(name)
        if name == wf.initial_state:
            lines.append(f'    {nid}["{label} (start)"]')
        else:
            lines.append(f'    {nid}["{label}"]')
    for src, dst in wf.edges():
        lines.append(f"    {_m_id(src)} --> {_m_id(dst)}")
    return "\n".join(lines)


def display_graph(wf: Workflow) -> Any:
    """Render a Workflow as a Mermaid diagram in a Jupyter cell (or print text fallback)."""
    mermaid_src = _build_mermaid_source(wf)

    if not _HAS_IPYTHON:
        print(mermaid_src)
        return None

    html_str = (
        '<script src="https://cdn.jsdelivr.net/npm/mermaid/dist/mermaid.min.js"></script>\n'
        "<script>mermaid.initialize({startOnLoad:true});</script>\n"
        f'<pre class="mermaid">\n{mermaid_src}\n</pre>'
    )
    obj = _IPyHTML(html_str)
    _ipython_display(obj)
    return obj


def _event_type_badge(typ: str) -> str:
    colors: dict[str, str] = {
        "run_started": "bg-blue-100 text-blue-800",
        "state_entered": "bg-indigo-100 text-indigo-800",
        "structured_output": "bg-purple-100 text-purple-800",
        "tool_call": "bg-amber-100 text-amber-800",
        "tool_result": "bg-amber-50 text-amber-700",
        "run_completed": "bg-green-100 text-green-800",
        "run_failed": "bg-red-100 text-red-800",
        "run_paused": "bg-yellow-100 text-yellow-800",
        "transition": "bg-gray-100 text-gray-600",
    }
    cls = colors.get(typ, "bg-gray-100 text-gray-800")
    return f'<span class="inline-block px-2 py-0.5 text-xs font-semibold rounded {cls}">{html.escape(typ)}</span>'


def _render_payload_detail(typ: str, payload: dict[str, Any]) -> str:
    if typ == "run_started":
        parts = [f"<strong>workflow:</strong> {html.escape(str(payload.get('workflow_name', '')))}"]
        if payload.get("inputs"):
            parts.append(f"<strong>inputs:</strong> {html.escape(json.dumps(payload['inputs'], default=str))}")
        return " &middot; ".join(parts)

    if typ == "state_entered":
        return f"<strong>state:</strong> {html.escape(str(payload.get('state', '')))}"

    if typ == "structured_output":
        raw = json.dumps(payload, indent=2, default=str)
        escaped = html.escape(raw)
        return (
            "<details class='mt-1'><summary class='cursor-pointer text-sm text-purple-600'>show JSON</summary>"
            f"<pre class='bg-gray-50 p-2 rounded text-xs overflow-x-auto'>{escaped}</pre></details>"
        )

    if typ in ("tool_call", "tool_result"):
        raw = json.dumps(payload, indent=2, default=str)
        escaped = html.escape(raw)
        return f"<pre class='bg-gray-50 p-2 rounded text-xs overflow-x-auto mt-1'>{escaped}</pre>"

    if typ == "run_completed":
        status = payload.get("status", "completed")
        return f"<strong>status:</strong> {html.escape(status)}"

    if typ == "run_failed":
        err = payload.get("error", {})
        msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
        return f"<strong class='text-red-700'>error:</strong> {html.escape(msg)}"

    if payload:
        raw = json.dumps(payload, indent=2, default=str)
        return f"<pre class='bg-gray-50 p-2 rounded text-xs overflow-x-auto mt-1'>{html.escape(raw)}</pre>"
    return ""


def display_run(store: EventStore, run_id: str) -> Any:
    """Render a run timeline as styled HTML in a Jupyter cell."""
    events = store.load_events(run_id)

    rows: list[str] = []
    for i, ev in enumerate(events):
        typ = ev.get("type", "unknown")
        ts = ev.get("ts", "")
        payload = ev.get("payload") or {}
        badge = _event_type_badge(typ)
        detail = _render_payload_detail(typ, payload)

        border_class = "border-l-4 border-indigo-300" if typ == "state_entered" else "border-l-4 border-gray-200"

        rows.append(
            f'<div class="pl-4 py-2 {border_class} mb-1">'
            f'  <div class="flex items-center gap-2">'
            f'    <span class="text-xs text-gray-400 font-mono w-6 text-right">{i}</span>'
            f"    {badge}"
            f'    <span class="text-xs text-gray-400">{html.escape(ts)}</span>'
            f"  </div>"
            f'  <div class="ml-8 text-sm">{detail}</div>'
            f"</div>"
        )

    html_str = (
        '<script src="https://cdn.tailwindcss.com"></script>\n'
        f'<div class="font-sans max-w-3xl mx-auto p-4">'
        f'<h3 class="text-lg font-bold mb-3">Run <code class="text-indigo-600">{html.escape(run_id)}</code></h3>'
        + "\n".join(rows)
        + "</div>"
    )

    if not _HAS_IPYTHON:
        print(html_str)
        return None

    obj = _IPyHTML(html_str)
    _ipython_display(obj)
    return obj
