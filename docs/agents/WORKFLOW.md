# JARVIS - Workflow Architecture

JARVIS operates on a Directed Acyclic Graph (DAG) state machine for execution tasks.

## Nodes
1. **Orchestrator**: Decomposes user objective into a structured JSON plan of steps using agent docs, tools, and long-term memory.
2. **Researcher**: Gathers context if the orchestrator requests it before finalizing the plan.
3. **Executor**: Executes the steps sequentially, invoking the appropriate tools and handling human approval pauses.
4. **Validator**: Inspects the final state to ensure the objective was met.
5. **Recovery**: If a step fails, analyzes the error and replans or fixes the issue automatically.
6. **Controller**: The edge router that decides which node to transition to next.

## Execution Loop
`Objective -> Memory Recall & Context Assembly -> Orchestrator -> [Plan] -> Executor(Step 1) -> Executor(Step 2) -> ... -> Validator -> Experience Recording & Knowledge Update -> Done`
