def decide_action(analysis):
    if analysis["confidence"] < 0.6:
        return "notify"

    if analysis["severity"] == "high":
        return "alert"

    return "suggest"
