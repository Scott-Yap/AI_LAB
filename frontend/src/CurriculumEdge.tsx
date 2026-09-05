import {
  BaseEdge,
  EdgeLabelRenderer,
  getSmoothStepPath,
  type EdgeProps,
} from "@xyflow/react";
import { GRAPH_LAYOUT } from "./graphLayout";

export function CurriculumEdge(props: EdgeProps) {
  const { id, sourceX, sourceY, targetX, targetY, label, markerEnd, style } =
    props;
  let [path, labelX, labelY] = getSmoothStepPath({
    ...props,
    offset: 32,
    borderRadius: 12,
  });
  // Skipped rows need a lane beside the nodes; a straight vertical edge crosses them.
  if (targetY - sourceY > GRAPH_LAYOUT.rowStep) {
    const laneX = sourceX + GRAPH_LAYOUT.columnStep / 2;
    const exitY = sourceY + 32;
    const enterY = targetY - 32;
    path = `M ${sourceX},${sourceY} L ${sourceX},${exitY} L ${laneX},${exitY} L ${laneX},${enterY} L ${targetX},${enterY} L ${targetX},${targetY}`;
    labelX = laneX;
    labelY = (exitY + enterY) / 2;
  }
  return (
    <>
      <BaseEdge id={id} path={path} markerEnd={markerEnd} style={style} />
      {label && (
        <EdgeLabelRenderer>
          <span
            className="graph-edge-label"
            style={{
              transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)`,
            }}
          >
            {label}
          </span>
        </EdgeLabelRenderer>
      )}
    </>
  );
}
