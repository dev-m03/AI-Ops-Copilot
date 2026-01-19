from db.client import supabase

def store_memory(project_id, incident_id, content, embedding):
    supabase.table("incident_memory").insert({
        "project_id": project_id,
        "incident_id": incident_id,
        "content": content,
        "embedding": embedding
    }).execute()
