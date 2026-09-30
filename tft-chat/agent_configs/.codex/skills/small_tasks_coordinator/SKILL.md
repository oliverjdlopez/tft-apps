---
name: small-tasks-coordinator
description: Coordinate independent tasks listed in SMALLTASKS.md by investigating scope, dispatching agents, and integrating their changes.
---

# Small Tasks Coordinator

Read `SMALLTASKS.md`, which contains scoped, well-defined tasks.

For each task, conduct a preliminary investigation to understand the broader context. Use that information to check whether the tasks are independent and can be implemented and merged in any order. If tasks depend on one another, ask the user to clarify the intended order and scope. Steps that are clearly subtasks of one parent task do not need this clarification.

Once independence is verified or the user provides direction, dispatch one subagent per task in an independent worktree. Give each subagent a concise context scaffold: include the task statement, relevant findings, and useful starting points. Let the subagent conduct its own deeper investigation; avoid steering its implementation decisions prematurely.

After all subagents return, combine their changes. Resolve trivial conflicts that do not affect functionality. If conflicts are significant, stop and report them to the user.

Apply the final diffs to the head of the current branch and leave them uncommitted. Report an overview of each subagent’s work.

If the branch has received committed or uncommitted changes since dispatch, and the final diffs still fit the original branch state, combine the changes into one coherent diff but keep it in the independent worktree rather than applying it to the branch. Report this to the user.