import logging
import json
from typing import Optional, List, Dict, Any
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
            try:
                experiences = self.hindsight.recall_relevant_experiences(
                    user_id=user_id,
                    objective=objective or "",
                    project_id=project_id,
                    limit=10
                )
            except Exception as e:
                logger.error(f"MEMORY_PROVIDER_ERROR: Failed to recall experiences for reflection - {e}")
                return

            if not experiences:
                logger.info("MEMORY_EMPTY: No recent experiences found for reflection.")
                return

            exp_texts = []
            for i, e in enumerate(experiences):
                exp_id = e.get("id", f"exp_{i}")
                exp_texts.append(f"ID: {exp_id}\nExperience:\n{e.get('content', '')}")
            
            recent_history = "\n\n---\n".join(exp_texts)

            # 2. Get existing preferences
            try:
                existing_prefs = self.okf.get_user_knowledge(user_id, "preferences").get("content", "")
            except Exception as e:
                logger.error(f"MEMORY_PROVIDER_ERROR: Failed to retrieve existing OKF preferences - {e}")
                return

            # 3. Call LLM Gateway
            system_prompt = (
                "You are JARVIS's internal memory reflector.\n"
                "Review the recent experiences and identify durable user preferences.\n\n"
                "RULES:\n"
                "- Distinguish explicit preferences (e.g. 'I prefer X') from inferred patterns.\n"
                "- Do NOT promote one-time behavior or weak inferences into permanent knowledge.\n"
                "- Provide a confidence_score (1-100).\n"
                "- Only identify durable information supported by the supplied experiences.\n"
                "- Return NO candidates if evidence is insufficient.\n"
                "- NEVER invent evidence IDs.\n"
                "- NEVER infer sensitive information.\n"
                "- Do NOT repeat existing preferences.\n\n"
                "OUTPUT FORMAT:\n"
                "You must return ONLY valid structured JSON matching this schema exactly, and nothing else:\n"
                "{\n"
                '  "candidates": [\n'
                '    {\n'
                '      "fact": "string",\n'
                '      "type": "explicit_preference" or "inferred_pattern",\n'
                '      "confidence_score": int,\n'
                '      "evidence_count": int,\n'
                '      "evidence": ["string (IDs)"]\n'
                '    }\n'
                '  ]\n'
                "}"
            )
            
            user_prompt = f"Existing preferences:\n{existing_prefs}\n\nRecent Experiences:\n{recent_history}"
            
            try:
                raw_response, _ = call_llm(
                    system=system_prompt,
                    user=user_prompt
                    # Automatically uses the Worker Gateway failover mechanism
                )
            except Exception as e:
                logger.error(f"REFLECTION_LLM_ERROR: LLM Gateway failed during reflection - {e}")
                return
            
            # 4. Parse and Validate Response
            try:
                start = raw_response.find("{")
                end = raw_response.rfind("}")
                if start == -1 or end == -1:
                    logger.info("REFLECTION_NO_CANDIDATES: No JSON found in response.")
                    return
                    
                parsed = json.loads(raw_response[start:end+1])
                candidates = parsed.get("candidates", [])
                
                if not candidates:
                    logger.info("REFLECTION_NO_CANDIDATES: JSON contained empty candidates list.")
                    return
                    
                valid_new_facts = []
                for cand in candidates:
                    # Schema Validation
                    fact = cand.get("fact")
                    c_type = cand.get("type")
                    conf = cand.get("confidence_score", 0)
                    e_count = cand.get("evidence_count", 0)
                    evidence = cand.get("evidence", [])
                    
                    if not fact or not isinstance(fact, str):
                        continue
                        
                    # Confidence Validation
                    if not isinstance(conf, (int, float)) or conf < 80:
                        continue
                        
                    # Evidence Count Validation and Explicit Preference distinction
                    if e_count < 2 and c_type != "explicit_preference":
                        # Reject weak inference
                        continue
                    
                    if c_type == "explicit_preference" and e_count < 1:
                        # Reject even explicit if 0 evidence
                        continue
                        
                    # Secret redaction check
                    if "sk-" in fact.lower() or "bearer" in fact.lower() or "api_key" in fact.lower():
                        continue
                        
                    valid_new_facts.append(fact)

                if valid_new_facts:
                    updated_prefs = existing_prefs + "\n" + "\n".join(f"- {f}" for f in valid_new_facts)
                    self.okf.update_user_knowledge(user_id, "preferences", updated_prefs.strip())
                    logger.info(f"Promoted {len(valid_new_facts)} facts to OKF preferences for {user_id}")
                else:
                    logger.info("REFLECTION_NO_CANDIDATES: Candidates rejected during validation.")
                    
            except json.JSONDecodeError as parse_e:
                logger.warning(f"REFLECTION_LLM_ERROR: Failed to parse reflection JSON: {parse_e}")
            except Exception as okf_e:
                logger.error(f"MEMORY_PROVIDER_ERROR: Failed to update OKF - {okf_e}")
                
        except Exception as e:
            logger.error(f"REFLECTION_ERROR: Unhandled error in memory reflection - {e}")
