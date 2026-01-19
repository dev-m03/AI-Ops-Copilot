import secrets

def generate_api_key():
    return "ops_" + secrets.token_hex(16)
