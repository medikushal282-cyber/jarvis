import asyncio
from dotenv import load_dotenv

load_dotenv()
from app.runtime.protocols import RunRequest
from app.runtime.events.emitter import get_emitter
from app.agent.brain import get_brain

async def run():
    brain = get_brain()
    req = RunRequest(
        run_id="test_basic_run",
        session_id="test_session",
        user_id="test_user",
        workspace_id="default",
        objective="Create a file called hello.txt containing Hello JARVIS in the current directory."
    )
    emit = get_emitter(req.run_id)
    out = await brain.run(req, emit)
    print("Outcome:", out.status)
    print("Reply:", out.reply)

if __name__ == "__main__":
    asyncio.run(run())
