import asyncio
from app.runtime.protocols import RunRequest
from app.runtime.events.emitter import get_emitter
from app.agent.brain import get_brain
from app.memory.api import get_user_knowledge

async def run_test():
    brain = get_brain()
    
    print("=== INTERACTION 1 ===")
    req1 = RunRequest(
        run_id="test_run_1",
        session_id="test_session",
        user_id="test_user",
        workspace_id="test_ws",
        objective="I prefer compact technical reports. Create a short report about this project.",
    )
    emit1 = get_emitter(req1.run_id)
    
    out1 = await brain.run(req1, emit1)
    print("OUTCOME 1:", out1.status, out1.reply)
    
    knowledge = get_user_knowledge("test_user")
    print("USER KNOWLEDGE AFTER 1:", knowledge)
    
    print("=== INTERACTION 2 ===")
    req2 = RunRequest(
        run_id="test_run_2",
        session_id="test_session",
        user_id="test_user",
        workspace_id="test_ws",
        objective="Create another report about this project using the usual format.",
    )
    emit2 = get_emitter(req2.run_id)
    
    # We can also check if context recall actually injected it
    mem_ctx = await brain.memory.recall(
        user_id=req2.user_id,
        objective=req2.objective,
        session_id=req2.session_id,
        workspace_id=req2.workspace_id
    )
    print("RECALLED MEMORY FOR 2:", mem_ctx)
    
    out2 = await brain.run(req2, emit2)
    print("OUTCOME 2:", out2.status, out2.reply)

if __name__ == "__main__":
    asyncio.run(run_test())
