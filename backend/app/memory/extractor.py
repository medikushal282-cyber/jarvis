import re
from typing import Dict, Any

class MemoryExtractor:
    """
    Extracts concise, meaningful experiences from raw execution state.
    """
    
    @staticmethod
    def _redact_secrets(text: str) -> str:
        """
        Redacts potential API keys, secrets, or large base64 blobs.
        """
        if not text:
            return text
        # Redact generic Bearer tokens
        text = re.sub(r'(?i)bearer\s+[a-zA-Z0-9_\-\.]{20,}', 'Bearer [REDACTED]', text)
        # Redact generic potential API keys (heuristic)
        text = re.sub(r'(?i)(api[_-]?key|secret|password|token)["\s:=]+[a-zA-Z0-9_\-\.]{15,}', r'\1=[REDACTED]', text)
        # Redact very long base64-like strings (over 200 chars)
        text = re.sub(r'[a-zA-Z0-9+/#]{200,}={0,2}', '[LARGE_BLOB_REDACTED]', text)
        return text

    @staticmethod
    def extract_experience(objective: str, execution_state: Dict[str, Any]) -> str:
        """
        Condenses a large execution state into a meaningful summary.
        """
        status = execution_state.get("status", "unknown")
        error = execution_state.get("error")
        artifacts = execution_state.get("artifacts", [])
        tool_calls = execution_state.get("tool_calls", [])
        
        summary_lines = [
            f"Task: {MemoryExtractor._redact_secrets(objective)}",
            f"Outcome: {status.upper()}"
        ]
        
        if error:
            error_str = MemoryExtractor._redact_secrets(str(error))
            summary_lines.append(f"Encountered Error: {error_str}")
            
        if artifacts:
            created = [a.get("path") for a in artifacts if a.get("path")]
            if created:
                summary_lines.append(f"Produced Artifacts: {', '.join(created)}")
                
        # Look for commands that failed, etc.
        failed_tools = [t for t in tool_calls if t.get("status") == "failed"]
        if failed_tools:
            failures = []
            for t in failed_tools:
                tool_name = t.get('tool', 'unknown')
                reason = MemoryExtractor._redact_secrets(str(t.get('reason', 'unknown error')))
                failures.append(f"{tool_name} ({reason})")
            summary_lines.append(f"Tool Failures: {'; '.join(failures)}")
            
        return "\n".join(summary_lines)
