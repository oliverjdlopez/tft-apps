/**
 * Decode the framed text/event stream emitted by the ChatTFT API.
 *
 * Keeping this parser framework-free makes fragmented transport behavior easy
 * to test and keeps the browser message component focused on rendering.
 */

export const STREAM_EVENT_PREFIX = "[[chat_tft_event:";
export const STREAM_EVENT_SUFFIX = "]]";

/**
 * Format one displayable assistant stream part for the chat transcript.
 *
 * The chat view applies this at the browser stream boundary so activity-panel
 * events remain unmodified and each visible part keeps its arrival order.
 *
 * @param {string} content Assistant text received in one displayable part.
 * @param {number} count One-based displayable-part count for the response.
 * @returns {string} Markdown with the requested label and paragraph spacing.
 */
export function formatChatPart(content, count) {
  return `\n\n**response ${count}**\n\n${content}`;
}

function preserveEventPrefixFragment(value) {
  const max = Math.min(STREAM_EVENT_PREFIX.length - 1, value.length);
  for (let length = max; length > 0; length -= 1) {
    const tail = value.slice(-length);
    if (STREAM_EVENT_PREFIX.startsWith(tail)) {
      return [value.slice(0, -length), tail];
    }
  }
  return [value, ""];
}

function decodeEventPayload(payload) {
  const bytes = Uint8Array.from(atob(payload), (character) => character.charCodeAt(0));
  return JSON.parse(new TextDecoder().decode(bytes));
}

/**
 * Consume all complete frames from a mixed response chunk.
 *
 * @param {string} buffer Text plus any pending partial frame.
 * @returns {{text: string, events: object[], pending: string, segments: object[]}}
 */
export function consumeStreamBuffer(buffer) {
  let rest = buffer;
  let text = "";
  const events = [];
  const segments = [];
  const appendText = (value) => {
    if (!value) return;
    text += value;
    const previous = segments.at(-1);
    if (previous?.type === "text") previous.value += value;
    else segments.push({ type: "text", value });
  };
  while (rest.length) {
    const start = rest.indexOf(STREAM_EVENT_PREFIX);
    if (start === -1) {
      const [ready, pending] = preserveEventPrefixFragment(rest);
      appendText(ready);
      rest = pending;
      break;
    }
    appendText(rest.slice(0, start).replace(/\n$/, ""));
    const eventStart = start + STREAM_EVENT_PREFIX.length;
    const eventEnd = rest.indexOf(STREAM_EVENT_SUFFIX, eventStart);
    if (eventEnd === -1) {
      rest = rest.slice(start);
      break;
    }
    try {
      const event = decodeEventPayload(rest.slice(eventStart, eventEnd));
      events.push(event);
      segments.push({ type: "event", value: event });
    } catch {
      // Invalid frames remain visible as text instead of taking down chat.
      appendText(rest.slice(start, eventEnd + STREAM_EVENT_SUFFIX.length));
    }
    rest = rest.slice(eventEnd + STREAM_EVENT_SUFFIX.length).replace(/^\n/, "");
  }
  return { text, events, pending: rest, segments };
}

export function parseAssistant(raw) {
  const errMatch = raw.match(/\[error\]\s*([^\n]*)/);
  const error = errMatch ? errMatch[1] : null;
  const text = raw
    .replace(/\[error\][^\n]*\n?/g, "")
    .replace(/\s*\[error[^\]\n]*$/i, "");
  return { text, error };
}
