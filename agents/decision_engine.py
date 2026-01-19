"""Agent decision engine."""
from app.agents.policies import decide_action
from app.agents.action_executor import execute_action

def run_agent(incident: dict, analysis: dict) -> dict:
    """Run decision engine on incident analysis."""
    action = decide_action(analysis)
    
    result = {
        "incident_id": incident.get("id"),
        "action": action,
        "executed": False,
        "message": None
    }
    
    # Execute approved actions
    if action in ["alert", "notify"]:
        try:
            executed = execute_action(action, incident, analysis)
            result["executed"] = executed
            result["message"] = f"Action '{action}' executed"
        except Exception as e:
            result["message"] = f"Action execution failed: {str(e)}"
    
    return result
