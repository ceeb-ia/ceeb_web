"""Small HTML plot manifests for the pattern-master engine."""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any, Iterable

from calendaritzacions.engine.variants.resource_solver.pattern_master.types import HubPattern, MicroHub, MasterSelection


def build_prerun_plot_payload(
    output_dir: Path,
    hubs: Iterable[MicroHub],
    patterns: Iterable[HubPattern],
    *,
    context: Any | None = None,
) -> dict[str, Any]:
    plot_dir = output_dir / "plots_pattern_master_prerun"
    plot_dir.mkdir(parents=True, exist_ok=True)
    hubs_tuple = tuple(hubs)
    patterns_tuple = tuple(patterns)
    network_path = plot_dir / "microhub_network.html"
    hub_path = plot_dir / "microhub_summary.html"
    pattern_path = plot_dir / "pattern_summary.html"
    _write_network_html(
        network_path,
        "Xarxa microhubs recursos + linkages",
        *_microhub_network(hubs_tuple),
        note="Hubs units a recursos, linkages i competicions tocades. Les competicions no connecten hubs en aquesta fase.",
    )
    _write_table_html(
        hub_path,
        "Microhubs recursos + linkages",
        [
            {
                "hub": hub.hub_id,
                "teams": len(hub.team_ids),
                "resources": len(hub.resource_keys),
                "linkages": len(hub.linkage_keys),
                "competitions": len(hub.competition_keys),
            }
            for hub in hubs_tuple
        ],
    )
    _write_table_html(
        pattern_path,
        "Patterns generats",
        [
            {
                "pattern": pattern.pattern_id,
                "hub": pattern.hub_id,
                "variant": pattern.variant,
                "teams": len(pattern.assignments),
                "cost": pattern.cost,
            }
            for pattern in patterns_tuple
        ],
    )
    plots = {
        "microhub_network": str(network_path),
    }
    if context is not None:
        plots.update(_decomposition_3d_plots(output_dir, hubs_tuple, context))
    return {
        "artifact_type": "resource_solver_pattern_master_prerun_plots",
        "plots": plots,
        "notes": [
            "Pre-run: hubs construits nomes amb recursos i linkages; competicions no connecten hubs.",
            "component_graph_3d usa el mateix generador interactiu que el motor conflict-repair.",
        ],
    }


def build_graph_plot_payload(output_dir: Path, compatibility_payload: dict[str, Any]) -> dict[str, Any]:
    plot_dir = output_dir / "plots_pattern_master_graph"
    plot_dir.mkdir(parents=True, exist_ok=True)
    network_path = plot_dir / "compatibility_network.html"
    graph_path = plot_dir / "compatibility_graph.html"
    conflicts = compatibility_payload.get("conflicts") if isinstance(compatibility_payload, dict) else []
    _write_network_html(
        network_path,
        "Xarxa constraints de patterns",
        *_compatibility_network(compatibility_payload),
        note="Nodes verds: constraints agregades que condicionen el mestre. Les capacitats no es converteixen en exclusions parell-a-parell.",
    )
    _write_table_html(
        graph_path,
        "Incompatibilitats dures de patterns",
        [
            {
                "left": row.get("left_pattern_id", ""),
                "right": row.get("right_pattern_id", ""),
                "reason": row.get("reason", ""),
            }
            for row in conflicts
            if isinstance(row, dict)
        ],
        empty="No hi ha incompatibilitats parell-a-parell. Les restriccions agregades continuen actives al mestre.",
    )
    return {
        "artifact_type": "resource_solver_pattern_master_graph_plots",
        "plots": {
            "compatibility_network": str(network_path),
        },
    }


def build_postrun_plot_payload(
    output_dir: Path,
    selection: MasterSelection,
    selected_patterns: Iterable[HubPattern],
    result: Any,
) -> dict[str, Any]:
    plot_dir = output_dir / "plots_pattern_master_postrun"
    plot_dir.mkdir(parents=True, exist_ok=True)
    network_path = plot_dir / "selected_patterns_network.html"
    selected_path = plot_dir / "selected_patterns.html"
    status_path = plot_dir / "postrun_status.html"
    selected_tuple = tuple(selected_patterns)
    _write_network_html(
        network_path,
        "Patterns seleccionats",
        *_selected_pattern_network(selected_tuple),
        note="Cada hub apunta al pattern triat pel mestre.",
    )
    _write_table_html(
        selected_path,
        "Patterns seleccionats pel mestre",
        [
            {
                "pattern": pattern.pattern_id,
                "hub": pattern.hub_id,
                "variant": pattern.variant,
                "teams": len(pattern.assignments),
                "cost": pattern.cost,
            }
            for pattern in selected_tuple
        ],
    )
    _write_kv_html(
        status_path,
        "Resultat pattern-master",
        {
            "master_status": selection.status,
            "selected_patterns": len(selected_tuple),
            "materialization_status": getattr(result, "status", ""),
            "assignments": len(getattr(result, "assignments", ()) or ()),
            "resource_excess": sum(int(getattr(usage, "excess", 0) or 0) for usage in getattr(result, "resource_usage", ()) or ()),
        },
    )
    return {
        "artifact_type": "resource_solver_pattern_master_postrun_plots",
        "plots": {
            "selected_patterns_network": str(network_path),
        },
    }


def _microhub_network(hubs: tuple[MicroHub, ...]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []
    for hub in hubs:
        hub_id = f"hub:{hub.hub_id}"
        nodes[hub_id] = {"id": hub_id, "label": hub.hub_id, "kind": "hub", "weight": max(4, len(hub.team_ids))}
        for key in hub.resource_keys:
            node_id = f"resource:{key}"
            nodes.setdefault(node_id, {"id": node_id, "label": str(key), "kind": "resource", "weight": 2})
            edges.append({"source": hub_id, "target": node_id, "kind": "resource"})
        for key in hub.linkage_keys:
            node_id = f"linkage:{key}"
            nodes.setdefault(node_id, {"id": node_id, "label": str(key), "kind": "linkage", "weight": 3})
            edges.append({"source": hub_id, "target": node_id, "kind": "linkage"})
        for key in hub.competition_keys:
            node_id = f"competition:{key}"
            nodes.setdefault(node_id, {"id": node_id, "label": str(key), "kind": "competition", "weight": 2})
            edges.append({"source": hub_id, "target": node_id, "kind": "competition"})
    return list(nodes.values()), edges


def _compatibility_network(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []
    conflicts = payload.get("conflicts", []) if isinstance(payload, dict) else []
    for row in conflicts if isinstance(conflicts, list) else []:
        if not isinstance(row, dict):
            continue
        left = str(row.get("left_pattern_id", ""))
        right = str(row.get("right_pattern_id", ""))
        if not left or not right:
            continue
        nodes.setdefault(left, {"id": left, "label": left, "kind": "pattern", "weight": 3})
        nodes.setdefault(right, {"id": right, "label": right, "kind": "pattern", "weight": 3})
        edges.append({"source": left, "target": right, "kind": "conflict"})

    constraints = payload.get("aggregate_constraints", []) if isinstance(payload, dict) else []
    for index, row in enumerate(constraints if isinstance(constraints, list) else [], start=1):
        if not isinstance(row, dict):
            continue
        pattern_ids = [str(item) for item in row.get("pattern_ids", []) if item]
        if not pattern_ids:
            continue
        constraint_id = f"constraint:{index}"
        label = f"{row.get('competition_key', '')} #{row.get('number', '')}"
        nodes[constraint_id] = {"id": constraint_id, "label": label, "kind": "constraint", "weight": min(10, len(pattern_ids))}
        for pattern_id in pattern_ids[:80]:
            nodes.setdefault(pattern_id, {"id": pattern_id, "label": pattern_id, "kind": "pattern", "weight": 3})
            edges.append({"source": constraint_id, "target": pattern_id, "kind": "aggregate"})
    return list(nodes.values()), edges


def _selected_pattern_network(patterns: tuple[HubPattern, ...]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []
    for pattern in patterns:
        hub_id = f"hub:{pattern.hub_id}"
        pattern_id = f"pattern:{pattern.pattern_id}"
        nodes[hub_id] = {"id": hub_id, "label": pattern.hub_id, "kind": "hub", "weight": len(pattern.assignments)}
        nodes[pattern_id] = {
            "id": pattern_id,
            "label": pattern.pattern_id,
            "kind": "selected",
            "weight": max(3, int(pattern.cost or 0) // 50 + 3),
        }
        edges.append({"source": hub_id, "target": pattern_id, "kind": "selected"})
    return list(nodes.values()), edges


def _decomposition_3d_plots(output_dir: Path, hubs: tuple[MicroHub, ...], context: Any) -> dict[str, str]:
    try:
        from calendaritzacions.reporting.resource_solver_decomposition_plots import (
            write_resource_solver_decomposition_plots,
        )
    except Exception:
        return {}
    components = [
        {
            "component_id": hub.hub_id,
            "team_count": len(hub.team_ids),
            "competition_count": len(hub.competition_keys),
            "resource_count": len(hub.resource_keys),
            "linkage_count": len(hub.linkage_keys),
            "candidate_count": _candidate_count_for_hub(context, hub),
            "team_ids": hub.team_ids,
            "competition_keys": hub.competition_keys,
            "resource_ids": hub.resource_keys,
            "linkage_keys": hub.linkage_keys,
        }
        for hub in hubs
    ]
    plots = write_resource_solver_decomposition_plots(
        output_dir / "plots_pattern_master_microhubs_3d",
        summary={"components": components},
        context=context,
        stem="pattern_master_microhubs",
    )
    return {
        plot_id: path
        for plot_id, path in plots.items()
        if plot_id == "component_graph_3d"
    }


def _candidate_count_for_hub(context: Any, hub: MicroHub) -> int:
    team_ids = set(hub.team_ids)
    return sum(1 for candidate in getattr(context, "candidates", ()) if getattr(candidate, "team_id", "") in team_ids)


def _write_table_html(path: Path, title: str, rows: list[dict[str, Any]], *, empty: str = "Sense files.") -> None:
    headers = sorted({key for row in rows for key in row}) if rows else []
    body = ""
    if rows and headers:
        head = "".join(f"<th>{html.escape(str(header))}</th>" for header in headers)
        rendered_rows = []
        for row in rows:
            cells = "".join(f"<td>{html.escape(str(row.get(header, '')))}</td>" for header in headers)
            rendered_rows.append(f"<tr>{cells}</tr>")
        body = f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(rendered_rows)}</tbody></table>"
    else:
        body = f"<p>{html.escape(empty)}</p>"
    path.write_text(_html_doc(title, body), encoding="utf-8")


def _write_network_html(
    path: Path,
    title: str,
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    *,
    note: str = "",
) -> None:
    graph = {"nodes": nodes, "edges": edges}
    data = _json_script_payload(graph)
    counts = f"{len(nodes)} nodes · {len(edges)} arestes"
    body = (
        f"<p class='note'>{html.escape(note)}</p>"
        f"<div class='toolbar'><span>{html.escape(counts)}</span>"
        "<button type='button' id='fit'>Recentrar</button></div>"
        "<canvas id='graph' width='1280' height='760'></canvas>"
        f"<script type='application/json' id='graph-data'>{data}</script>"
        "<script>"
        "const payload=JSON.parse(document.getElementById('graph-data').textContent);"
        "const canvas=document.getElementById('graph');const ctx=canvas.getContext('2d');"
        "const colors={hub:'#2563eb',resource:'#f97316',linkage:'#dc2626',competition:'#7c3aed',pattern:'#64748b',constraint:'#16a34a',selected:'#0891b2'};"
        "let nodes=payload.nodes.map((n,i)=>({...n,x:0,y:0,vx:0,vy:0,index:i}));"
        "let byId=new Map(nodes.map(n=>[n.id,n]));"
        "let edges=payload.edges.map(e=>({...e,source:byId.get(e.source),target:byId.get(e.target)})).filter(e=>e.source&&e.target);"
        "let zoom=1,panX=0,panY=0,drag=null,dragPan=null;"
        "function init(){const r=Math.min(canvas.width,canvas.height)*0.35;nodes.forEach((n,i)=>{const a=2*Math.PI*i/Math.max(1,nodes.length);n.x=canvas.width/2+Math.cos(a)*r;n.y=canvas.height/2+Math.sin(a)*r;});}"
        "function step(){for(const n of nodes){n.vx*=0.82;n.vy*=0.82;}"
        "for(let i=0;i<nodes.length;i++){for(let j=i+1;j<nodes.length;j++){const a=nodes[i],b=nodes[j];let dx=a.x-b.x,dy=a.y-b.y,d2=Math.max(dx*dx+dy*dy,80);let f=Math.min(900/d2,3);a.vx+=dx*f;a.vy+=dy*f;b.vx-=dx*f;b.vy-=dy*f;}}"
        "for(const e of edges){const a=e.source,b=e.target;let dx=b.x-a.x,dy=b.y-a.y,d=Math.max(Math.hypot(dx,dy),1);let wanted=e.kind==='conflict'?95:140;let f=(d-wanted)*0.012;a.vx+=dx/d*f;a.vy+=dy/d*f;b.vx-=dx/d*f;b.vy-=dy/d*f;}"
        "for(const n of nodes){n.vx+=(canvas.width/2-n.x)*0.002;n.vy+=(canvas.height/2-n.y)*0.002;if(n!==drag){n.x+=n.vx;n.y+=n.vy;}}}"
        "function project(n){return{x:n.x*zoom+panX,y:n.y*zoom+panY};}"
        "function radius(n){return Math.max(5,Math.min(18,5+Math.sqrt(Number(n.weight||2))*2));}"
        "function draw(){ctx.clearRect(0,0,canvas.width,canvas.height);ctx.lineCap='round';"
        "for(const e of edges){const a=project(e.source),b=project(e.target);ctx.beginPath();ctx.moveTo(a.x,a.y);ctx.lineTo(b.x,b.y);ctx.strokeStyle=e.kind==='conflict'?'rgba(220,38,38,.34)':e.kind==='aggregate'?'rgba(22,163,74,.22)':'rgba(71,85,105,.25)';ctx.lineWidth=e.kind==='conflict'?1.4:1;ctx.stroke();}"
        "const visible=nodes.slice().sort((a,b)=>radius(a)-radius(b));"
        "for(const n of visible){const p=project(n),r=radius(n);ctx.beginPath();ctx.arc(p.x,p.y,r,0,Math.PI*2);ctx.fillStyle=colors[n.kind]||'#334155';ctx.fill();ctx.strokeStyle='white';ctx.lineWidth=2;ctx.stroke();}"
        "ctx.font='11px Inter,Arial,sans-serif';ctx.fillStyle='#0f172a';"
        "for(const n of visible.filter(n=>radius(n)>8||nodes.length<90)){const p=project(n);ctx.fillText(String(n.label||n.id).slice(0,38),p.x+radius(n)+4,p.y+4);}}"
        "function tick(){for(let i=0;i<3;i++)step();draw();requestAnimationFrame(tick);}"
        "function mousePos(ev){const rect=canvas.getBoundingClientRect();return{x:(ev.clientX-rect.left)*canvas.width/rect.width,y:(ev.clientY-rect.top)*canvas.height/rect.height};}"
        "canvas.addEventListener('mousedown',ev=>{const m=mousePos(ev);drag=null;for(const n of nodes){const p=project(n);if(Math.hypot(m.x-p.x,m.y-p.y)<=radius(n)+5){drag=n;break;}}if(!drag)dragPan={x:m.x,y:m.y,px:panX,py:panY};});"
        "canvas.addEventListener('mousemove',ev=>{const m=mousePos(ev);if(drag){drag.x=(m.x-panX)/zoom;drag.y=(m.y-panY)/zoom;drag.vx=0;drag.vy=0;}else if(dragPan){panX=dragPan.px+m.x-dragPan.x;panY=dragPan.py+m.y-dragPan.y;}});"
        "window.addEventListener('mouseup',()=>{drag=null;dragPan=null;});"
        "canvas.addEventListener('wheel',ev=>{ev.preventDefault();const factor=ev.deltaY>0 ? .9 : 1.1;zoom=Math.max(.25,Math.min(4,zoom*factor));},{passive:false});"
        "document.getElementById('fit').addEventListener('click',()=>{zoom=1;panX=0;panY=0;init();});"
        "init();tick();"
        "</script>"
    )
    path.write_text(_html_doc(title, body, network=True), encoding="utf-8")


def _json_script_payload(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False).replace("</", "<\\/")


def _write_kv_html(path: Path, title: str, values: dict[str, Any]) -> None:
    rows = "".join(
        f"<tr><th>{html.escape(str(key))}</th><td>{html.escape(str(value))}</td></tr>"
        for key, value in values.items()
    )
    path.write_text(_html_doc(title, f"<table><tbody>{rows}</tbody></table>"), encoding="utf-8")


def _html_doc(title: str, body: str, *, network: bool = False) -> str:
    extra = (
        "canvas{width:100%;height:760px;border:1px solid #d8dee4;border-radius:8px;background:#f8fafc}"
        ".toolbar{display:flex;justify-content:space-between;align-items:center;margin:10px 0 12px;color:#475569}"
        "button{border:1px solid #cbd5e1;background:white;border-radius:6px;padding:6px 10px;cursor:pointer}"
        ".note{color:#475569}"
        if network
        else ""
    )
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>{html.escape(title)}</title>"
        "<style>body{font-family:Inter,Arial,sans-serif;margin:24px;color:#1f2933}"
        "table{border-collapse:collapse;width:100%;font-size:13px}"
        "th,td{border:1px solid #d8dee4;padding:6px 8px;text-align:left}"
        f"th{{background:#f3f6f8}}{extra}</style></head><body>"
        f"<h1>{html.escape(title)}</h1>{body}</body></html>"
    )


__all__ = [
    "build_graph_plot_payload",
    "build_postrun_plot_payload",
    "build_prerun_plot_payload",
]
