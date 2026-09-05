import type { Concept } from "./types";

// Presentation grid only: never rewrite persisted curriculum positions or relationships.
export const GRAPH_LAYOUT = {
  columnStep: 320,
  rowStep: 200,
};

export function spacedPositions(concepts: Concept[]) {
  const columns = [...new Set(concepts.map((n) => n.position.x))].sort(
    (a, b) => a - b,
  );
  const rows = [...new Set(concepts.map((n) => n.position.y))].sort(
    (a, b) => a - b,
  );
  return concepts.map((node) => ({
    ...node,
    position: {
      x: columns.indexOf(node.position.x) * GRAPH_LAYOUT.columnStep,
      y: rows.indexOf(node.position.y) * GRAPH_LAYOUT.rowStep,
    },
  }));
}
