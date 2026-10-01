/** Serial routing worker. The UI terminates superseded jobs and rejects stale generations. */
import { routeDiagram } from './routing.js';
self.onmessage = ({ data: { generation, graph } }) => {
  try {
    const routes = routeDiagram(graph, (progress) => self.postMessage({ generation, progress }));
    self.postMessage({ generation, routes });
  } catch (error) { self.postMessage({ generation, error: error.message }); }
};
