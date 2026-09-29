from unittest.mock import patch
import asyncio
from app.runtime.protocols import RunRequest
from app.runtime.protocols import RunOutcome
from app.runtime.events.emitter import get_emitter
from app.agent.brain import get_brain
from app.memory.api import get_user_knowledge
import json

def mock_call_llm(system, user, *args, **kwargs):
    print(f"MOCK LLM CALLED:\nSystem: {system[:50]}...\nUser: {user[:50]}...")
    if "reflect" in system.lower() or "durable" in system.lower():
        # MemoryReflector
        return json.dumps({
            "promotions": [
                {
                    "topic": "preferences",
                    "content": "User explicitly prefers compact technical reports.",
                    "confidence": 95,
                    "evidence": ["User objective: I prefer compact technical reports."]
                }
            ],
            "observations": []
        }), None
    else:
        # MemoryExtractor
        return "This was a successful run where the user requested compact reports.", None

async def mock_run_agent_loop(request, emit, memory_context=None):
    if 'compact' in request.objective.lower():
        reply = 'Here is your compact report.'
    else:
        if memory_context and 'compact' in str(memory_context.get('user_knowledge', '')):
            reply = 'Here is your report, formatting compactly as preferred.'
        elif memory_context and any('compact' in e.get('content', '') for e in memory_context.get('experiences', [])):
            reply = 'Here is your report, formatting compactly based on recent experience.'
        else:
            reply = 'Here is your report in normal long format.'
    return RunOutcome(status='completed', reply=reply)

async def run_test():
    brain = get_brain()
    
    print("=== INTERACTION 1 ===")
    req1 = RunRequest(
        run_id="test_run_1",
        session_id="test_session",
        user_id="test_user",
        workspace_id="test_ws",
        objective="I prefer compact technical reports. Create a short report about this project."
    )
    emit1 = get_emitter(req1.run_id)
    
    with patch('app.agent.brain.run_agent_loop', new=mock_run_agent_loop):
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
        objective="Create another report about this project using the usual format."
    )
    emit2 = get_emitter(req2.run_id)
    
    mem_ctx = await brain.memory.recall(
        user_id=req2.user_id,
        objective=req2.objective,
        session_id=req2.session_id,
        workspace_id=req2.workspace_id
    )
    print("RECALLED MEMORY FOR 2:", mem_ctx)
    
    with patch('app.agent.brain.run_agent_loop', new=mock_run_agent_loop):
        out2 = await brain.run(req2, emit2)
        print("OUTCOME 2:", out2.status, out2.reply)

if __name__ == "__main__":
    with patch('app.memory.extractor.call_llm', new=mock_call_llm):
        with patch('app.memory.reflection.call_llm', new=mock_call_llm):
            asyncio.run(run_test())
