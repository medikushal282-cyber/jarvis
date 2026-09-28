# JARVIS - Planning Guidelines

When the Orchestrator generates a plan, it MUST follow these rules:

1. **Dependency Awareness**: Steps must correctly list `depends_on` IDs. Do not try to read a file before the step that creates it has run.
2. **Granularity**: Break complex objectives down. Don't write 5 files in one step. One tool action = one step.
3. **Self-Correction**: If a plan fails mid-execution, the Recovery node will generate a patch plan. 
4. **Previewing**: If the objective involves UI or HTML changes, the final step should be `OPEN_BROWSER` to launch the live preview.
