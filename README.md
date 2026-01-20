# AI Ops Copilot — Developer Documentation

AI Ops Copilot is a lightweight, AI-powered incident analysis platform that plugs into any backend with a single API key. It ingests logs, groups incidents, performs AI-driven root cause analysis, and triggers safe automated actions.

---

## 🚀 Getting Started

### 1. Create an Account

* Visit the AI Ops Copilot website : www.aiopsco.vercel.app
* Sign up using email & password
* Log in to access your dashboard

---

## 📦 Create a Project & API Key

1. Go to **Dashboard**
2. Click **Create Project**
3. Enter a project name
4. Copy the generated **API Key**

> 🔐 Keep this key secret. It is write-only and scoped to your project.

---

## 🔑 Environment Variables

```env
AIOPS_API_KEY=ops_xxxxxxxxx
AIOPS_ENDPOINT=https://aiops-api.onrender.com/logs
```

---

## 📡 Log Ingestion API

### Endpoint

```
POST https://aiops-api.onrender.com/logs
```

### Headers

```
X-API-Key: <your_api_key>
Content-Type: application/json
```

### Request Body

```json
{
  "service": "auth-service",
  "level": "ERROR",
  "message": "Database connection timeout",
  "metadata": {
    "path": "/login",
    "method": "POST"
  }
}
```

### Response

```json
{
  "status": "ok"
}
```

---

## ⚙️ Backend Integration Examples

### FastAPI (Python)

```python
import os, requests
from fastapi import FastAPI, Request

app = FastAPI()

@app.middleware("http")
async def aiops_logger(request: Request, call_next):
    try:
        return await call_next(request)
    except Exception as e:
        requests.post(
            "https://aiops-api.onrender.com/logs",
            headers={"X-API-Key": os.getenv("AIOPS_API_KEY")},
            json={
                "service": "fastapi-app",
                "level": "ERROR",
                "message": str(e),
                "metadata": {
                    "path": request.url.path,
                    "method": request.method
                }
            },
            timeout=2
        )
        raise
```

---

### Spring Boot (Java)

```java
@RestControllerAdvice
public class GlobalExceptionHandler {

  @Value("${aiops.api-key}")
  private String apiKey;

  @ExceptionHandler(Exception.class)
  public void handle(Exception ex, HttpServletRequest req) {
    RestTemplate rest = new RestTemplate();
    HttpHeaders headers = new HttpHeaders();
    headers.set("X-API-Key", apiKey);
    headers.setContentType(MediaType.APPLICATION_JSON);

    Map<String, Object> body = Map.of(
      "service", "springboot-app",
      "level", "ERROR",
      "message", ex.getMessage(),
      "metadata", Map.of(
        "path", req.getRequestURI(),
        "method", req.getMethod()
      )
    );

    rest.postForEntity(
      "https://aiops-api.onrender.com/logs",
      new HttpEntity<>(body, headers),
      String.class
    );
  }
}
```

---

### Node.js (Express)

```js
import axios from "axios";

app.use(async (err, req, res, next) => {
  await axios.post("https://aiops-api.onrender.com/logs", {
    service: "node-app",
    level: "ERROR",
    message: err.message,
    metadata: {
      path: req.path,
      method: req.method
    }
  }, {
    headers: {
      "X-API-Key": process.env.AIOPS_API_KEY
    },
    timeout: 2000
  });

  res.status(500).send("Internal Server Error");
});
```

---

## 🧠 Incident Lifecycle

```
Logs → Incidents → AI Analysis → Agent Decision
```

* Logs are grouped into incidents automatically
* AI performs root cause analysis
* A decision engine triggers safe actions
* Results are visible in the dashboard

---

## 🤖 AI Root Cause Analysis

AI Ops Copilot uses an LLM (Gemini) with:

* Strict JSON output
* Confidence scoring
* Severity classification
* Human-in-the-loop safeguards

If analysis is unreliable, the system **fails safely** and flags for review.

---

## 🗂 Incident Memory (RAG)

The `incident_memory` table is reserved for **validated incidents only**.

* AI output is **not** stored blindly
* Memory is written after human confirmation
* Enables future similarity search (RAG)

---

## 🔐 Security Model

* API keys are **project-scoped**
* No user JWTs for log ingestion
* Write-only access
* Keys are revocable
* All requests are authenticated

---

## 📊 Dashboard Features

* Project management
* API key generation
* Incident list
* AI analysis per incident
* Action execution logs

---

## 🧪 Testing Without Production Traffic

You can test ingestion using:

* Swagger
* Postman
* Simple scripts (curl / requests / axios)

Each request creates an incident visible in the dashboard.

---

## 🏁 Summary

AI Ops Copilot is designed to:

* Integrate in minutes
* Stay language-agnostic
* Operate safely with AI
* Scale from MVP to production

---

For issues or contributions, refer to the GitHub repository.

Happy shipping 🚀
