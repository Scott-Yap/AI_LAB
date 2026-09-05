import { useMemo, useState } from "react";
import {
  Background,
  Controls,
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  type NodeProps,
} from "@xyflow/react";
import { ArrowUpRight, BookOpen, Search, X } from "lucide-react";
import type { Concept, Graph } from "./types";
import "@xyflow/react/dist/style.css";
import { CurriculumEdge } from "./CurriculumEdge";
import { spacedPositions } from "./graphLayout";

function ConceptNode({ data, selected }: NodeProps) {
  return (
    <div className={`concept-node ${selected ? "selected" : ""}`}>
      <Handle type="target" position={Position.Top} />
      <span className="node-chapter">{String(data.chapter)}</span>
      <strong>{String(data.label)}</strong>
      <Handle type="source" position={Position.Bottom} />
    </div>
  );
}
const nodeTypes = { concept: ConceptNode };
const edgeTypes = { curriculum: CurriculumEdge };

export function KnowledgeGraph({
  graph,
  selected,
  onSelect,
  onLearn,
  busy,
}: {
  graph: Graph;
  selected: Concept | null;
  onSelect: (node: Concept | null) => void;
  onLearn: (node: Concept) => void;
  busy: boolean;
}) {
  const [search, setSearch] = useState("");
  const nodes = useMemo(
    () =>
      spacedPositions(graph.nodes).map((node) => ({
        id: node.id,
        position: node.position,
        type: "concept",
        selected: selected?.id === node.id,
        data: { label: node.name, chapter: node.chapter },
        style: {
          opacity:
            !search || node.name.toLowerCase().includes(search.toLowerCase())
              ? 1
              : 0.2,
        },
      })),
    [graph, selected, search],
  );
  const edges = useMemo(
    () =>
      graph.edges.map((edge) => ({
        ...edge,
        type: "curriculum",
        label:
          selected &&
          (edge.source === selected.id || edge.target === selected.id)
            ? edge.relationship.replaceAll("_", " ")
            : "",
        markerEnd: { type: MarkerType.ArrowClosed, color: "var(--graph-edge)" },
        style: { stroke: "var(--graph-edge)", strokeWidth: 1.4 },
      })),
    [graph, selected],
  );
  return (
    <section className="graph-panel" aria-label="Knowledge graph">
      <div className="panel-heading">
        <div>
          <span className="eyebrow">YOUR LEARNING MAP</span>
          <h2>Everything connects.</h2>
        </div>
        <span className="count-pill">{graph.nodes.length} concepts</span>
      </div>
      <label className="graph-search">
        <Search size={15} />
        <input
          aria-label="Find a concept"
          placeholder="Find a concept…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        {search && (
          <button
            aria-label="Clear concept search"
            onClick={() => setSearch("")}
          >
            <X size={14} />
          </button>
        )}
      </label>
      {search && (
        <div className="concept-results">
          {graph.nodes
            .filter((n) => n.name.toLowerCase().includes(search.toLowerCase()))
            .map((n) => (
              <button
                key={n.id}
                onClick={() => {
                  onSelect(n);
                  setSearch("");
                }}
              >
                {n.name}
                <ArrowUpRight size={13} />
              </button>
            ))}
          {!graph.nodes.some((n) =>
            n.name.toLowerCase().includes(search.toLowerCase()),
          ) && <span>No matching concepts</span>}
        </div>
      )}
      <div className="graph-canvas">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          edgeTypes={edgeTypes}
          defaultViewport={{ x: 25, y: 20, zoom: 0.8 }}
          minZoom={0.25}
          maxZoom={1.6}
          nodesDraggable={false}
          nodesConnectable={false}
          onNodeClick={(_, node) =>
            onSelect(graph.nodes.find((n) => n.id === node.id) ?? null)
          }
          onPaneClick={() => onSelect(null)}
        >
          <Background gap={22} size={1} color="var(--graph-dot)" />
          <Controls showInteractive={false} />
        </ReactFlow>
      </div>
      {selected ? (
        <div className="concept-detail">
          <div className="detail-top">
            <span className="eyebrow">{selected.chapter} · CONCEPT</span>
            <button
              aria-label="Close concept details"
              onClick={() => onSelect(null)}
            >
              <X size={16} />
            </button>
          </div>
          <h3>{selected.name}</h3>
          <p>{selected.description}</p>
          <span className="section-reference">
            <BookOpen size={14} />
            {selected.section}
          </span>
          <button
            className="primary learn-button"
            disabled={busy}
            onClick={() => onLearn(selected)}
          >
            Learn this concept <ArrowUpRight size={17} />
          </button>
        </div>
      ) : (
        <div className="graph-hint">
          <span className="small-orbit">✳</span>
          <p>
            <strong>Follow your curiosity.</strong>
            <br />
            Select a concept to see its connections and start learning.
          </p>
        </div>
      )}
      <div className="graph-footer">
        <span>
          <i /> Curriculum connections
        </span>
        <span>Pan · Zoom · Explore</span>
      </div>
    </section>
  );
}
