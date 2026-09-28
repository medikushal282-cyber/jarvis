from typing import Dict, Any

class MemoryExtractor:
    """
    Extracts concise, meaningful experiences from raw execution state.
    """
    
    @staticmethod
    def extract_experience(objective: str, execution_state: Dict[str, Any]) -> str:
        """
        Condenses a large execution state into a meaningful summary.
        """
        # A real implementation would use an LLM or advanced heuristics to summarize.
        # For this mock, we will pull out artifacts, errors, and key tool calls.
        
        status = execution_state.get("status", "unknown")
        error = execution_state.get("error")
        artifacts = execution_state.get("artifacts", [])
        tool_calls = execution_state.get("tool_calls", [])
        
        summary_lines = [
            f"Task: {objective}",
            f"Outcome: {status.upper()}"
        ]
        
        if error:
            summary_lines.append(f"Encountered Error: {error}")
            
        if artifacts:
            created = [a.get("path") for a in artifacts if a.get("path")]
            if created:
                summary_lines.append(f"Produced Artifacts: {', '.join(created)}")
                
        # Look for commands that failed, etc.
        failed_tools = [t for t in tool_calls if t.get("status") == "failed"]
        if failed_tools:
            failures = [f"{t.get('tool', 'unknown')} ({t.get('reason', 'unknown error')})" for t in failed_tools]
            summary_lines.append(f"Tool Failures: {'; '.join(failures)}")
            
        return "\n".join(summary_lines)
