/** Canvas-wide editing callbacks, catalog lookups, and edge style shared by custom nodes and edges. */
import { createContext, useContext } from "react";

export const FlowchartContext = createContext({
  readOnly: true,
  catalog: new Map(),
  edgeStyle: "step",
  updateNodeData: () => {},
  updateEdgeData: () => {},
});

export const useFlowchart = () => useContext(FlowchartContext);
