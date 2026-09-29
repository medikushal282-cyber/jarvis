import asyncio
from dotenv import load_dotenv
load_dotenv()
from app.llm.router import call_llm

async def main():
    system = "You are JARVIS. Reply with exactly OK."
    user = "Say OK."
    
    try:
        response, _ = call_llm(system=system, user=user)
        print("MINIMAL LLM TEST RESULT:")
        print(response)
    except Exception as e:
        print("MINIMAL LLM TEST FAILED:")
        print(e)

if __name__ == "__main__":
    asyncio.run(main())
