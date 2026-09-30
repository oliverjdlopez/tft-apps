Read the SMALLTASKS.md file. It contains requests for some scoped and well-defined tasks. 

For each task, do some preliminary background investigation yourself to understand the broader picture. 


As a rule of thumb, SMALLTASKS.md is meant to carry indendent tasks, meaning that they can be implemented and merged without conflicts in any order.
Use the details from your preliminary investigations to determine if any of the tasks are not independent. If they are not, ask for clarification from the user regarding implementation order and intent. 
Note: if tasks or steps are given implicitly to be subtasks of a single parent tasks, then those are considered subtasks and you don't have to flag questions for independence. 

Once you have verified task independence, or received further direction from the user, dispatch a subagent for each task, **in an independent worktree.** Use your preliminary investigation materials to scope out the task for them. 
Your instructions to the subagents should be built to give them a context scaffold for the task statement. Each subagent will proceed to conduct a deeper investigation than your preliminary investigation, so 
your instructions to them should be meant to give them a kickstart and first step directions. Do not write anything that will disproportionately bias their decisions ahead of time since they will end up with more 
expertise in that area than yourself by the time that they are done.

Once all of the subagents have returned, merge their changes together. You should resolve yourself any
trivial conflicts which dont actually affect functionality. For significant conflicts, stop and report to the user. 

Once you have the final diffs, apply them to the head of this branch, but leave uncommitted. Report back to the user which an overview of what the subagents did. 

If the final diffs are consistent with the old branch state but in the time since dispatch there have been committed or uncommitted changes to this branch,
then still proceed to combine the changes of the subagents into a single coherent diff, but do not apply it to this branch. Keep it in its own worktree. Report back to the user with this update.