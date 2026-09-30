# Everyday evaluation workflow

To create a separately named assistant dataset, use the
[dataset registration command](langfuse-content.md#create-another-assistant-dataset).

1. Open Langfuse at `http://localhost:15500`, choose **Datasets**, and open
   **end-to-end**, **data-analysis**, or **context-response**. The last suite
   uses deterministic response checks rather than native answer-quality grading.
2. Add a case with application input and a readable expected result. A chat
   input is the string `"Your request"`. Object wrappers are rejected. Metadata
   is optional for scored cases.
   For assistant cases tied to a TFT set, add `{"database":"your_database_name"}`
   to the item's **Metadata**, retaining existing fields. Old and new set cases
   can use different databases in the same experiment; see
   [database selection](langfuse-content.md#keep-cases-from-multiple-tft-sets).
3. In **Prompts**, save a candidate version. Keep the reviewed `baseline` label
   on the baseline version. Editing a candidate does not change the application.
4. Open the dataset's **Experiments → Run experiment → via Webhook** dialog.
   The default runs one baseline. To compare a candidate, use advanced JSON:

   ```json
   {
     "assistant": "chat",
     "variants": [
       {"name":"baseline"},
       {"name":"candidate","prompts":{"chat":{"name":"chattft/assistants/chat","version":2}}}
     ]
   }
   ```

   Replace `2` with your candidate's actual version. `assistant` selects the
   entry assistant for this run; omit it to use the dataset default. For a
   direct analyst run, use `"assistant": "data_analyst"` and target
   `data_analyst` in the candidate prompt map. The Python service
   executes the full workflow; this is not a prompt-only experiment.
   Imported intake cases now live in **end-to-end**, with `scoring: "none"`
   in metadata. They skip grading while other cases retain their normal checks.
5. For scored datasets, wait for scoring. Assistant completion can precede
   quality grades. Inspect
   `chattft-experiment-job` observations for `awaiting_scores`, final success,
   or a failure reason. Missing grades do not count as success.
6. Select baseline and candidate experiments and choose **Compare**. Read actual
   outputs alongside quality dimensions, `execution_success`, `contract_pass`,
   and final `attempt_pass`. Use **Columns** to keep these acceptance scores
   prominent; individual diagnostics remain inspectable on each trace. Inspect
   cost and latency on generation observations.
7. Open a failing item's trace. Inspect tool arguments/results, handoffs,
   deterministic explanations, and native evaluator reasoning. The comment icon
   beside a score badge opens its explanation. A presentation
   tool's data is inspectable even though Langfuse does not render ChatTFT widgets.
8. Add the item to **ChatTFT review**, record human acceptance and a failure
   category, and correct the case reference or evaluator when appropriate.

## Capture a development regression

Enable `[chat] langfuse_tracing = true` with optional evaluation dependencies and
Langfuse credentials. Find the conversation in the `development` environment and
use **Add to dataset** to capture a single-message regression in `end-to-end`.
Replace the captured conversation object with the user-message string before
saving; multi-turn histories are not accepted by these datasets. Keep its source
observation link, write expected requirements, then replay it through the same
Custom Experiment path. Conversations are neither auto-added nor auto-judged.

## Advanced maintenance

Use **export** or **replay** in the advanced webhook payload, or the commands in
[content and snapshots](langfuse-content.md). Compare runs with the same frozen
cases and evaluator definitions. Definition drift makes a run non-comparable;
restore historical evaluators into an isolated replay project when necessary.
Keep a separately [reviewed baseline](langfuse-content.md#reproducibility).

## Edit → run → inspect in Playground

For quick single-prompt iteration, open **Prompts → your assistant → Playground
→ Fresh playground**. Select the **ChatTFT backend** connection and the matching
model, for example **chattft/unit_expert**. Put the assistant instructions in a
**System** message and add a **User** message with your test question. Edit the
system text and click **Submit** (or **Run All**); you do not need a dataset,
snapshot, baseline run, or backend restart between edits. Save useful drafts as prompt versions using
the Playground's prompt controls.

This connection executes this checkout's actual assistant graph, registered
tools, and typed `RDS_EVAL_*` database. The model selector chooses the entry
assistant; its underlying LLM comes from the backend configuration. System and
developer messages replace that assistant's base instructions for this request;
normal context assembly still applies. Other reachable assistants retain their
repository prompts. Select `chattft/chat` for the complete chat workflow or a
specialist such as `chattft/unit_expert` to test that specialist directly.

The answer includes **Inspect ChatTFT run: tools, handoffs, and prompts** and a
trace URL. In Langfuse 4.35.0 the output is plain text: copy the URL into a browser
tab. It selects the root observation with your exact draft messages, final
answer, database name, and instruction hashes. The tree on the left exposes model
calls, tool arguments/results, and handoffs. Alternatively, find the latest
`chattft-playground` trace under **Tracing** and select its root observation. Failed executions link to their error trace. Playground replies
arrive after the graph finishes; a keepalive stream prevents an idle connection
from expiring. ChatTFT presentation widgets remain inspectable tool data.

Temperature, top-p, token limits, and frequency/presence penalties, when set,
are passed to the graph's LLM calls (subject to that provider's support). Leave
optional parameters unset to preserve backend defaults. Text-only conversation
history is supported; custom Playground tools and structured-output controls
are rejected rather than silently ignored. The backend owns tool definitions.
This connection is for assistant testing; keep evaluators on their ordinary LLM
connection. Dataset Custom Experiments remain the scored comparison workflow,
except for the explicitly registered unscored prompt-intake dataset.
