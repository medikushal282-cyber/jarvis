import logging
import json
from typing import Optional
from .hindsight.adapter import HindsightAdapter
from .okf.manager import OKFManager
from app.llm.router import call_llm

logger = logging.getLogger(__name__)

class MemoryReflector:
    """
    Reflects on recent experiences to promote recurring patterns
    to durable structured knowledge (OKF).
    """
    def __init__(self, hindsight: Optional[HindsightAdapter] = None, okf: Optional[OKFManager] = None):
        self.hindsight = hindsight or HindsightAdapter()
        self.okf = okf or OKFManager()

    def reflect(self, user_id: str, objective: Optional[str] = None, project_id: Optional[str] = None):
        """
        Lightweight reflection over recent experiences to identify durable preferences.
        """
        try:
            # 1. Fetch recent experiences
            experiences = self.hindsight.recall_relevant_experiences(
                user_id=user_id,
                objective=objective or "",
                project_id=project_id,
                limit=10  # Look at the last 10 relevant items
            )
            
            if not experiences:
                return

            exp_texts = []
            for i, e in enumerate(experiences):
                exp_texts.append(f"Experience {i+1}:\n{e.get('content', '')}")
            
            recent_history = "\n\n".join(exp_texts)

            # 2. Get existing preferences to avoid duplication/contradiction
            existing_prefs = self.okf.get_user_knowledge(user_id, "preferences").get("content", "")

            # 3. Call LLM to identify new durable facts
            system_prompt = (
                "You are JARVIS's internal memory reflector.\n"
                "Review the recent experiences and identify if there is any explicit user preference "
                "or recurring pattern that should become durable knowledge.\n"
                "Return ONLY a JSON array of strings containing new clear facts, e.g. [\"User prefers PDF output for reports\"].\n"
                "If there is nothing new or durable, return [].\n"
                "Do NOT repeat existing preferences."
            )
            
            user_prompt = f"Existing preferences:\n{existing_prefs}\n\nRecent Experiences:\n{recent_history}"
            
            raw_response, _ = call_llm(
                system=system_prompt,
                user=user_prompt,
                model="gpt-4o-mini", # Use a fast/cheap model for reflection
                provider="openai"
            )
            
            # 4. Parse response
            try:
                # Find JSON array bracket
                start = raw_response.find("[")
                end = raw_response.rfind("]")
                if start != -1 and end != -1:
                    new_facts = json.loads(raw_response[start:end+1])
                    if isinstance(new_facts, list) and new_facts:
                        # Append to OKF
                        updated_prefs = existing_prefs + "\n" + "\n".join(f"- {f}" for f in new_facts if isinstance(f, str))
                        self.okf.update_user_knowledge(user_id, "preferences", updated_prefs.strip())
                        logger.info(f"Promoted {len(new_facts)} facts to OKF preferences for {user_id}")
            except Exception as parse_e:
                logger.warning(f"Failed to parse reflection response: {parse_e}")
                
        except Exception as e:
            logger.error(f"Reflection failed gracefully: {e}")
