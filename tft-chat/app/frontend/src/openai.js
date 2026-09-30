/** Build the OpenAI dashboard URL for one exact Agents SDK trace. */
export function openAiTraceUrl(traceId) {
  return `https://platform.openai.com/traces/trace?trace_id=${encodeURIComponent(traceId)}`;
}
