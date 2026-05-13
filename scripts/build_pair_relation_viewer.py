"""
Phase D-2 ビューア生成スクリプト

pair_relations.json と entity_opinions.json をブラウザで fetch して表示する
force-directed viewer HTML を生成する。

HTML 自体にはデータを埋め込まず、静的ホスティングでも相対パスの JSON を読む前提。
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PAIRS_JSON = ROOT / "data/pair_relations.json"
DEFAULT_OPINIONS_JSON = ROOT / "data/entity_opinions.json"
DEFAULT_OUTPUT_HTML = ROOT / "pair_relation_viewer.html"

SENTIMENT_COLOR = {
    "positive": "#4ade80",
    "negative": "#f87171",
    "mixed": "#fb923c",
    "neutral": "#94a3b8",
}

EDGE_COLOR = "#60a5fa"


def relative_url(from_path: Path, to_path: Path) -> str:
    rel = os.path.relpath(to_path, start=from_path.parent)
    return rel.replace(os.sep, "/")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pairs-json", type=Path, default=DEFAULT_PAIRS_JSON)
    parser.add_argument("--opinions-json", type=Path, default=DEFAULT_OPINIONS_JSON)
    parser.add_argument("--output-html", type=Path, default=DEFAULT_OUTPUT_HTML)
    cli = parser.parse_args()

    pairs_url = relative_url(cli.output_html, cli.pairs_json)
    opinions_url = relative_url(cli.output_html, cli.opinions_json)
    sent_colors_json = json.dumps(SENTIMENT_COLOR, ensure_ascii=False)
    edge_color = EDGE_COLOR

    html = f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>エンティティ関係マップ（ペアレベル）</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/d3/7.9.0/d3.min.js"></script>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: sans-serif; background: #1a1a2e; color: #e0e0e0;
       height: 100vh; overflow: hidden; display: flex; flex-direction: column; }}
#toolbar {{ background: #16213e; padding: 6px 14px; border-bottom: 1px solid #0f3460;
           display: flex; align-items: center; gap: 10px; flex-shrink: 0; flex-wrap: wrap; }}
#toolbar h1 {{ font-size: 0.88rem; color: #e0e0e0; white-space: nowrap; }}
label {{ font-size: 0.72rem; color: #aaa; white-space: nowrap; }}
input[type=range] {{ width: 80px; vertical-align: middle; }}
input[type=text] {{ background: #0f172a; color: #e5e7eb; border: 1px solid #334155;
                    border-radius: 4px; padding: 4px 8px; font-size: 0.76rem; width: 220px; }}
button {{ background: #1e3a5f; color: #dbeafe; border: 1px solid #3b82f6;
         border-radius: 4px; padding: 4px 8px; font-size: 0.74rem; cursor: pointer; }}
button:hover {{ background: #234a76; }}
#stats {{ font-size: 0.67rem; color: #666; margin-left: auto; white-space: nowrap; }}
#legend {{ display: flex; gap: 6px; align-items: center; flex-wrap: wrap; border-left: 1px solid #2a3a5e; padding-left: 10px; }}
.leg {{ display: flex; align-items: center; gap: 3px; font-size: 0.67rem; color: #aaa; }}
.leg-dot {{ width: 9px; height: 9px; border-radius: 50%; flex-shrink: 0; }}
#main {{ flex: 1; display: flex; overflow: hidden; }}
#graph-area {{ flex: 1; position: relative; }}
svg {{ width: 100%; height: 100%; }}
.node text {{ fill: #ddd; font-size: 11px; pointer-events: none;
             text-shadow: 0 0 4px #000, 0 0 4px #000; }}
.node circle {{ stroke-width: 1.5px; cursor: pointer; transition: filter 0.1s; }}
.node circle:hover {{ filter: brightness(1.4); }}
.node circle.selected {{ stroke: #ffd700 !important; stroke-width: 2.5px; }}
.node circle.search-hit {{ stroke: #38bdf8 !important; stroke-width: 2.5px; }}
.node.search-dim {{ opacity: 0.23; }}
.link-path {{ fill: none; stroke-opacity: 0.65; cursor: pointer; transition: stroke-opacity 0.1s; }}
.link-path:hover {{ stroke-opacity: 1; stroke-width: 3 !important; }}
.link-path.selected-edge {{ stroke-opacity: 1; stroke-width: 3 !important; }}
.link-path.rescue-edge {{ stroke-dasharray: 5 4; stroke-opacity: 0.45; }}
#panel {{ width: 380px; background: #16213e; border-left: 1px solid #0f3460;
         overflow-y: auto; flex-shrink: 0; padding: 14px; font-size: 0.82rem; }}
#panel.hidden {{ display: none; }}
.panel-title {{ font-weight: bold; font-size: 0.92rem; color: #e0e0e0; margin-bottom: 10px; }}
.panel-section {{ margin-bottom: 12px; }}
.panel-lbl {{ font-size: 0.65rem; color: #666; margin-bottom: 4px;
             text-transform: uppercase; letter-spacing: 0.06em; }}
.panel-val {{ color: #ccc; line-height: 1.6; }}
.description-box {{ background: #1e2d4a; border-radius: 5px; padding: 9px 11px;
                   font-size: 0.8rem; color: #c8d8f0; line-height: 1.7; }}
.evidence-box {{ background: #1e2535; border-left: 3px solid #475569; padding: 7px 10px;
                font-size: 0.75rem; color: #94a3b8; line-height: 1.6; font-style: italic; }}
.opinion-point {{ background: #0f3460; border-radius: 4px; padding: 5px 9px;
                 margin-bottom: 4px; font-size: 0.76rem; line-height: 1.5; color: #c8d8f0; }}
.example-arg {{ background: #1e2535; border-left: 3px solid #475569; padding: 5px 9px;
               margin-bottom: 4px; font-size: 0.72rem; color: #94a3b8; line-height: 1.5; }}
.sent-badge {{ display: inline-block; border-radius: 4px; padding: 2px 8px;
              font-size: 0.71rem; font-weight: bold; margin-right: 4px; }}
.pair-rel-item {{ background: #1e2535; border-radius: 4px; padding: 7px 10px;
                 margin-bottom: 6px; border-left: 3px solid #60a5fa; }}
.pair-rel-title {{ font-size: 0.8rem; color: #e0e0e0; margin-bottom: 6px; }}
.pair-rel-actions {{ display: flex; gap: 8px; flex-wrap: wrap; }}
.pair-link-btn {{ background: transparent; border: none; padding: 0;
                 color: #7dd3fc; font-size: 0.72rem; cursor: pointer; }}
.pair-link-btn:hover {{ color: #bae6fd; text-decoration: underline; }}
.pair-sep {{ color: #64748b; font-size: 0.72rem; }}
.qid-link {{ color: #60a5fa; text-decoration: none; font-size: 0.71rem; }}
.qid-link:hover {{ text-decoration: underline; }}
.close-btn {{ float: right; cursor: pointer; color: #888; font-size: 1rem; }}
.close-btn:hover {{ color: #eee; }}
#loading {{ padding: 14px; font-size: 0.78rem; color: #94a3b8; }}
#error {{ padding: 14px; font-size: 0.78rem; color: #fca5a5; white-space: pre-wrap; }}
</style>
</head>
<body>
<div id="toolbar">
  <h1>エンティティ関係マップ</h1>
  <div id="legend">
    <span style="font-size:0.65rem;color:#555">sentiment:</span>
    <div class="leg"><div class="leg-dot" style="background:#4ade80"></div>positive</div>
    <div class="leg"><div class="leg-dot" style="background:#f87171"></div>negative</div>
    <div class="leg"><div class="leg-dot" style="background:#fb923c"></div>mixed</div>
    <div class="leg"><div class="leg-dot" style="background:#94a3b8"></div>neutral</div>
  </div>
  <label>検索:
    <input type="text" id="searchBox" placeholder="ノード名で検索">
  </label>
  <button id="searchGo" type="button">移動</button>
  <div id="searchStatus" style="font-size:0.67rem;color:#94a3b8"></div>
  <label>斥力: <input type="range" id="charge" min="-600" max="-30" value="-220"></label>
  <div id="stats">loading...</div>
</div>
<div id="main">
  <div id="graph-area">
    <div id="loading">データ読み込み中...</div>
    <svg id="svg"></svg>
  </div>
  <div id="panel" class="hidden">
    <span class="close-btn" onclick="closePanel()">✕</span>
    <div id="panelContent"></div>
  </div>
</div>

<script>
const PAIRS_URL = {json.dumps(pairs_url, ensure_ascii=False)};
const OPINIONS_URL = {json.dumps(opinions_url, ensure_ascii=False)};
const SENT_COLORS = {sent_colors_json};
const EDGE_COLOR = {json.dumps(edge_color)};

const svg = d3.select('#svg');
const g = svg.append('g');
const zoomBehavior = d3.zoom().scaleExtent([0.08, 8]).on('zoom', e => g.attr('transform', e.transform));
svg.call(zoomBehavior);

let sim, pathSel, nodeSel;
let currentLinks = [];
let selectedEdgeId = null;
let selectedNodeId = null;
let nodeById = {{}};
let NODES_RAW = [];
let EDGES_RAW = [];
let searchMatches = [];
let searchMatchIndex = 0;

function nodeRadius(n) {{
  return 6 + Math.sqrt(Math.max(n.comment_count || 1, 1)) * 1.8;
}}

function makePath(d, nodes) {{
  const src = typeof d.source === 'object' ? d.source : nodes.find(n => n.id === d.source);
  const tgt = typeof d.target === 'object' ? d.target : nodes.find(n => n.id === d.target);
  if (!src || !tgt) return '';

  const dx = tgt.x - src.x, dy = tgt.y - src.y;
  const len = Math.sqrt(dx*dx + dy*dy);
  if (len < 1) return '';

  const ux = dx/len, uy = dy/len;
  const nx = -uy, ny = ux;
  const rSrc = nodeRadius(src) + 1;
  const rTgt = nodeRadius(tgt) + 1;

  const sx = src.x + ux * rSrc, sy = src.y + uy * rSrc;
  const tx = tgt.x - ux * rTgt, ty = tgt.y - uy * rTgt;
  const curve = d.curvature || 0;
  const mx = (sx + tx) / 2 + nx * curve, my = (sy + ty) / 2 + ny * curve;

  return `M${{sx}},${{sy}} Q${{mx}},${{my}} ${{tx}},${{ty}}`;
}}

function buildData(pairsPayload, opinionsPayload) {{
  const pairs = pairsPayload.pairs || [];
  const opinions = opinionsPayload.entities || [];
  const idToOpinion = {{}};
  opinions.forEach(e => idToOpinion[e.id] = e);

  const nodes = opinions
    .slice()
    .sort((a, b) => (a.controlled_label || a.id).localeCompare(b.controlled_label || b.id, 'ja'))
    .map(op => {{
    const color = SENT_COLORS[op.sentiment || 'neutral'] || '#94a3b8';
    return {{
      id: op.id,
      controlled_label: op.controlled_label || op.id,
      type: op.type || 'wikidata',
      qid: op.qid,
      wikidata_desc: op.wikidata_desc || '',
      sentiment: op.sentiment || 'neutral',
      sentiment_reason: op.sentiment_reason || '',
      opinion_points: op.opinion_points || [],
      example_args: op.example_args || [],
      comment_count: op.comment_count || 0,
      item_ids: op.item_ids || [],
      surfaces: op.surfaces || [],
      color
    }};
  }});

  const edges = pairs
    .map(p => ({{
      id: p.pair_key,
      pair_key: p.pair_key,
      source: p.id_a,
      target: p.id_b,
      label_a: p.label_a,
      label_b: p.label_b,
      description: p.description || '',
      evidence: p.evidence || '',
      score: p.score || 0,
      shared_clusters: p.shared_clusters || 0,
      synthetic: p.selection_reason === 'connectivity_rescue'
    }}));

  const existingPairKeys = new Set(edges.map(e => e.pair_key));
  const relationSignals = {{}};

  function pairKey(a, b) {{
    return a < b ? `${{a}}|${{b}}` : `${{b}}|${{a}}`;
  }}

  opinions.forEach(op => {{
    (op.relations || []).forEach(rel => {{
      const targetId = rel.target_id;
      if (!targetId || targetId === op.id || !idToOpinion[targetId]) return;
      const key = pairKey(op.id, targetId);
      if (!relationSignals[key]) {{
        relationSignals[key] = {{ forward: 0, backward: 0 }};
      }}
      if (op.id < targetId) relationSignals[key].forward += 1;
      else relationSignals[key].backward += 1;
    }});
  }});

  const connectedIds = new Set();
  edges.forEach(e => {{
    connectedIds.add(e.source);
    connectedIds.add(e.target);
  }});

  const rescuedIds = new Set();
  nodes.forEach(node => {{
    if (connectedIds.has(node.id) || rescuedIds.has(node.id)) return;

    let best = null;
    Object.entries(relationSignals).forEach(([key, sig]) => {{
      const [idA, idB] = key.split('|');
      if (node.id !== idA && node.id !== idB) return;
      if (existingPairKeys.has(key)) return;

      const otherId = node.id === idA ? idB : idA;
      if (!idToOpinion[otherId]) return;

      const itemIdsA = new Set(node.item_ids || []);
      const itemIdsB = new Set(idToOpinion[otherId].item_ids || []);
      let shared = 0;
      itemIdsA.forEach(itemId => {{
        if (itemIdsB.has(itemId)) shared += 1;
      }});

      const opinionCount = sig.forward + sig.backward;
      const bidirectional = sig.forward > 0 && sig.backward > 0;
      const score = opinionCount + (bidirectional ? 3 : 0) + shared * 2;
      if (score <= 0) return;

      const candidate = {{
        pair_key: key,
        id_a: idA,
        id_b: idB,
        label_a: idToOpinion[idA].controlled_label || idA,
        label_b: idToOpinion[idB].controlled_label || idB,
        score,
        shared_clusters: shared,
        comment_count: Math.max(node.comment_count || 0, idToOpinion[otherId].comment_count || 0),
        description: '',
        evidence: '',
        synthetic: true,
      }};

      if (!best || candidate.score > best.score) best = candidate;
    }});

    if (best) {{
      edges.push({{
        id: best.pair_key,
        pair_key: best.pair_key,
        source: best.id_a,
        target: best.id_b,
        label_a: best.label_a,
        label_b: best.label_b,
        description: '',
        evidence: '',
        score: best.score,
        shared_clusters: best.shared_clusters,
        synthetic: true,
      }});
      existingPairKeys.add(best.pair_key);
      connectedIds.add(best.id_a);
      connectedIds.add(best.id_b);
      rescuedIds.add(best.id_a);
      rescuedIds.add(best.id_b);
    }}
  }});

  const stats = {{
    nodes: nodes.length,
    edges: edges.length,
    pairs: pairs.length,
    positive: nodes.filter(n => n.sentiment === 'positive').length,
    negative: nodes.filter(n => n.sentiment === 'negative').length,
    mixed: nodes.filter(n => n.sentiment === 'mixed').length,
    neutral: nodes.filter(n => n.sentiment === 'neutral').length,
  }};

  return {{ nodes, edges, stats }};
}}

function render() {{
  g.selectAll('*').remove();
  const edges = EDGES_RAW;
  const nodes = NODES_RAW.map(n => ({{ ...n }}));
  const nodeMap = {{}};
  nodes.forEach(n => nodeMap[n.id] = n);

  const links = edges
    .map(e => ({{
      ...e,
      source: typeof e.source === 'string' ? e.source : e.source.id,
      target: typeof e.target === 'string' ? e.target : e.target.id,
    }}))
    .filter(e => nodeMap[e.source] && nodeMap[e.target]);
  currentLinks = links;

  pathSel = g.append('g').selectAll('path.link-path')
    .data(links, d => d.id).join('path')
    .attr('class', d => `link-path${{d.synthetic ? ' rescue-edge' : ''}}${{d.id === selectedEdgeId ? ' selected-edge' : ''}}`)
    .attr('stroke', EDGE_COLOR)
    .attr('stroke-width', 2)
    .on('click', (ev, d) => {{ ev.stopPropagation(); showEdgePanel(d, nodes); }});

  nodeSel = g.append('g').selectAll('g.node')
    .data(nodes, d => d.id).join('g').attr('class', 'node')
    .call(d3.drag()
      .on('start', (ev, d) => {{ if (!ev.active) sim.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; }})
      .on('drag',  (ev, d) => {{ d.fx = ev.x; d.fy = ev.y; }})
      .on('end',   (ev, d) => {{ if (!ev.active) sim.alphaTarget(0); d.fx = null; d.fy = null; }}))
    .on('click', (ev, d) => {{ ev.stopPropagation(); showNodePanel(d, links); }});

  nodeSel.each(function(d) {{
    const r = nodeRadius(d);
    d3.select(this).append('circle').attr('r', r)
      .attr('fill', d.color)
      .attr('stroke', d3.color(d.color)?.darker(1.2) || '#333')
      .attr('stroke-width', 1.5)
      .classed('selected', d.id === selectedNodeId);
  }});

  nodeSel.append('text')
    .attr('dy', d => nodeRadius(d) + 12)
    .attr('text-anchor', 'middle')
    .text(d => d.controlled_label);

  if (sim) sim.stop();
  sim = d3.forceSimulation(nodes)
    .force('link', d3.forceLink(links).id(d => d.id).distance(100).strength(0.2))
    .force('charge', d3.forceManyBody().strength(+document.getElementById('charge').value))
    .force('center', d3.forceCenter(
      document.getElementById('graph-area').clientWidth / 2,
      document.getElementById('graph-area').clientHeight / 2))
    .force('collide', d3.forceCollide().radius(d => nodeRadius(d) + 12))
    .on('tick', () => {{
      pathSel.attr('d', d => makePath(d, nodes));
      nodeSel.attr('transform', d => `translate(${{d.x}},${{d.y}})`);
    }});
}}

function updateSelection() {{
  if (pathSel) pathSel.attr('class', d =>
    `link-path${{d.synthetic ? ' rescue-edge' : ''}}${{d.id === selectedEdgeId ? ' selected-edge' : ''}}`);
  if (nodeSel) {{
    const hasSearch = searchMatches.length > 0;
    nodeSel.classed('search-dim', d => hasSearch && !searchMatches.includes(d.id));
    nodeSel.select('circle')
      .classed('selected', d => d.id === selectedNodeId)
      .classed('search-hit', d => searchMatches.includes(d.id));
  }}
}}

function closePanel() {{
  document.getElementById('panel').classList.add('hidden');
  selectedEdgeId = null;
  selectedNodeId = null;
  updateSelection();
}}

function navigateToNode(nodeId) {{
  const node = nodeById[nodeId];
  if (node) showNodePanel(node, currentLinks);
}}

function navigateToPair(pairKey) {{
  const edge = currentLinks.find(link => link.pair_key === pairKey);
  if (edge) showEdgePanel(edge, NODES_RAW);
}}

function focusNode(nodeId) {{
  const node = nodeById[nodeId];
  if (!node || node.x == null || node.y == null) return;
  const graphArea = document.getElementById('graph-area');
  const width = graphArea.clientWidth;
  const height = graphArea.clientHeight;
  const scale = 1.4;
  const transform = d3.zoomIdentity
    .translate(width / 2 - node.x * scale, height / 2 - node.y * scale)
    .scale(scale);
  svg.transition().duration(350).call(zoomBehavior.transform, transform);
  showNodePanel(node, currentLinks);
}}

function sentBadge(sent) {{
  const col = SENT_COLORS[sent] || '#94a3b8';
  return `<span class="sent-badge" style="background:${{col}}22;color:${{col}};border:1px solid ${{col}}55">${{sent}}</span>`;
}}

function showEdgePanel(d, nodes) {{
  selectedEdgeId = d.id;
  selectedNodeId = null;
  updateSelection();

  const nA = nodeById[d.source?.id ?? d.source];
  const nB = nodeById[d.target?.id ?? d.target];
  const lblA = nA?.controlled_label || d.label_a;
  const lblB = nB?.controlled_label || d.label_b;

  document.getElementById('panelContent').innerHTML = `
    <div class="panel-title">${{lblA}} — ${{lblB}}</div>
    <div class="panel-section">
      <div class="panel-val">
        ${{d.synthetic ? '<span style="color:#fbbf24;font-size:0.65rem;margin-left:6px">補助リンク</span>' : ''}}
        <span style="color:#555;font-size:0.65rem;margin-left:6px">共通クラスタ ${{d.shared_clusters}}</span>
      </div>
    </div>
    <div class="panel-section">
      <div class="panel-lbl">ノード移動</div>
      <div class="pair-rel-actions">
        <button type="button" class="pair-link-btn" onclick="navigateToNode('${{nA?.id || d.source?.id || d.source}}')">
          ${{lblA}} へ
        </button>
        <span class="pair-sep">／</span>
        <button type="button" class="pair-link-btn" onclick="navigateToNode('${{nB?.id || d.target?.id || d.target}}')">
          ${{lblB}} へ
        </button>
      </div>
    </div>
    ${{d.description ? `
    <div class="panel-section">
      <div class="panel-lbl">関係の説明</div>
      <div class="description-box">${{d.description.replace(/\\n\\n/g, '<br><br>')}}</div>
    </div>` : ''}}
    ${{d.evidence ? `
    <div class="panel-section">
      <div class="panel-lbl">コメントからの根拠</div>
      <div class="evidence-box">${{d.evidence}}</div>
    </div>` : ''}}`;
  document.getElementById('panel').classList.remove('hidden');
}}

function showNodePanel(d, links) {{
  selectedNodeId = d.id;
  selectedEdgeId = null;
  updateSelection();

  const qidHtml = d.qid
    ? `<a class="qid-link" href="https://www.wikidata.org/wiki/${{d.qid}}" target="_blank">${{d.qid}} ↗</a>`
    : '<span style="color:#666">LOCAL</span>';

  const opHtml = (d.opinion_points || []).map(p =>
    `<div class="opinion-point">・${{p}}</div>`).join('') || '<span style="color:#555">なし</span>';

  const exHtml = (d.example_args || []).slice(0, 2).map(a =>
    `<div class="example-arg">${{a.slice(0, 200)}}${{a.length > 200 ? '…' : ''}}</div>`).join('');

  const myEdges = links.filter(e => {{
    const s = typeof e.source === 'string' ? e.source : e.source.id;
    const t = typeof e.target === 'string' ? e.target : e.target.id;
    return s === d.id || t === d.id;
  }});

  const pairMap = {{}};
  myEdges.forEach(e => {{
    const pk = e.pair_key;
    const s = typeof e.source === 'string' ? e.source : e.source.id;
    const t = typeof e.target === 'string' ? e.target : e.target.id;
    const otherId = s === d.id ? t : s;
    if (!pairMap[pk]) pairMap[pk] = {{ pairKey: pk, score: e.score, a: e.label_a, b: e.label_b, otherId }};
  }});

  const pairsHtml = Object.values(pairMap).sort((a, b) => b.score - a.score).map(p => {{
    const otherLbl = p.a === d.controlled_label ? p.b : p.a;
    return `<div class="pair-rel-item">
      <div class="pair-rel-title">${{otherLbl}}</div>
      <div class="pair-rel-actions">
        <button type="button" class="pair-link-btn" onclick="navigateToNode('${{p.otherId}}')">
          ノードへ
        </button>
        <span class="pair-sep">／</span>
        <button type="button" class="pair-link-btn" onclick="navigateToPair('${{p.pairKey}}')">
          関係を見る
        </button>
      </div>
    </div>`;
  }}).join('') || '<span style="color:#555">なし</span>';

  document.getElementById('panelContent').innerHTML = `
    <div class="panel-title">${{d.controlled_label}}</div>
    <div class="panel-section">
      <div class="panel-lbl">種別 / QID</div>
      <div class="panel-val">${{d.type === 'wikidata' ? '🔗 Wikidata' : '📝 LOCAL'}} ${{qidHtml}}</div>
    </div>
    ${{d.wikidata_desc ? `<div class="panel-section"><div class="panel-lbl">説明</div><div class="panel-val" style="color:#777;font-size:0.74rem">${{d.wikidata_desc}}</div></div>` : ''}}
    <div class="panel-section">
      <div class="panel-lbl">Sentiment (${{d.comment_count}} comments)</div>
      <div class="panel-val">${{sentBadge(d.sentiment)}} ${{d.sentiment_reason}}</div>
    </div>
    <div class="panel-section">
      <div class="panel-lbl">主な意見</div>
      ${{opHtml}}
    </div>
    <div class="panel-section">
      <div class="panel-lbl">関連ペア (${{Object.keys(pairMap).length}}件)</div>
      ${{pairsHtml}}
    </div>
    ${{exHtml ? `<div class="panel-section"><div class="panel-lbl">代表コメント</div>${{exHtml}}</div>` : ''}}`;
  document.getElementById('panel').classList.remove('hidden');
}}

document.getElementById('charge').addEventListener('input', () => {{
  if (sim) sim.force('charge', d3.forceManyBody().strength(
    +document.getElementById('charge').value)).alpha(0.3).restart();
}});

svg.on('click', closePanel);

function updateSearch() {{
  const q = normalizeSearchText(document.getElementById('searchBox').value);
  const status = document.getElementById('searchStatus');
  if (!q) {{
    searchMatches = [];
    searchMatchIndex = 0;
    status.textContent = '';
    updateSelection();
    return;
  }}

  searchMatches = NODES_RAW
    .filter(n => matchesSearch(n, q))
    .map(n => n.id);
  if (searchMatchIndex >= searchMatches.length) searchMatchIndex = 0;
  status.textContent = searchMatches.length ? `${{searchMatches.length}}件ヒット` : '0件';
  updateSelection();
}}

function normalizeSearchText(text) {{
  return (text || '')
    .toLowerCase()
    .replace(/\\s+/g, '')
    .replace(/付き/g, '付');
}}

function matchesSearch(node, normalizedQuery) {{
  const candidates = [
    node.controlled_label || '',
    node.id || '',
    ...(node.surfaces || []),
    node.wikidata_desc || '',
  ];
  return candidates.some(value => normalizeSearchText(value).includes(normalizedQuery));
}}

function goToSearchMatch() {{
  if (!searchMatches.length) return;
  const nodeId = searchMatches[searchMatchIndex % searchMatches.length];
  searchMatchIndex += 1;
  focusNode(nodeId);
}}

document.getElementById('searchBox').addEventListener('input', updateSearch);
document.getElementById('searchBox').addEventListener('keydown', ev => {{
  if (ev.key === 'Enter') {{
    ev.preventDefault();
    updateSearch();
    goToSearchMatch();
  }}
}});
document.getElementById('searchGo').addEventListener('click', () => {{
  updateSearch();
  goToSearchMatch();
}});

async function init() {{
  try {{
    const [pairsResp, opinionsResp] = await Promise.all([
      fetch(PAIRS_URL),
      fetch(OPINIONS_URL),
    ]);
    if (!pairsResp.ok || !opinionsResp.ok) {{
      throw new Error(`fetch failed: pairs=${{pairsResp.status}}, opinions=${{opinionsResp.status}}`);
    }}

    const [pairsPayload, opinionsPayload] = await Promise.all([
      pairsResp.json(),
      opinionsResp.json(),
    ]);
    const built = buildData(pairsPayload, opinionsPayload);
    NODES_RAW = built.nodes;
    EDGES_RAW = built.edges;
    nodeById = {{}};
    NODES_RAW.forEach(n => nodeById[n.id] = n);
    document.getElementById('stats').textContent =
      `ノード ${{built.stats.nodes}} | ペア ${{built.stats.pairs}}`;
    document.getElementById('loading')?.remove();
    render();
  }} catch (err) {{
    const loading = document.getElementById('loading');
    if (loading) {{
      loading.id = 'error';
      loading.textContent = `データ読み込み失敗\\n${{String(err)}}\\n\\nPAIRS_URL=${{PAIRS_URL}}\\nOPINIONS_URL=${{OPINIONS_URL}}`;
    }}
    document.getElementById('stats').textContent = 'load error';
  }}
}}

init();
</script>
</body>
</html>"""

    cli.output_html.parent.mkdir(parents=True, exist_ok=True)
    cli.output_html.write_text(html, encoding="utf-8")
    print(f"生成完了: {cli.output_html}")
    print(f"  fetch: {pairs_url}, {opinions_url}")


if __name__ == "__main__":
    main()
