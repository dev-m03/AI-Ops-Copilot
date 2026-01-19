"""Safe action executor for incidents."""
from app.services.notification_service import send_notification

def execute_action(action: str, incident: dict, analysis: dict) -> bool:
    """Execute approved action safely."""
    if action == "alert":
        return _send_alert(incident, analysis)
    elif action == "notify":
        return _send_notification(incident, analysis)
    elif action == "suggest":
        # Log suggestion for human review
        return True
    return False


def _send_alert(incident: dict, analysis: dict) -> bool:
    """Send critical alert."""
    message = f"""
🚨 *Critical Incident Alert*
Service: {incident.get('service')}
Severity: {analysis.get('severity')}
Root Cause: {analysis.get('root_cause')}
Confidence: {analysis.get('confidence', 0):.0%}
"""
    return send_notification(message)


def _send_notification(incident: dict, analysis: dict) -> bool:
    """Send informational notification."""
    message = f"""
📢 *Incident Notification*
Service: {incident.get('service')}
Issue: {incident.get('summary')}
Suggested Fixes: {', '.join(analysis.get('suggested_fixes', []))}
"""
    return send_notification(message)
    
