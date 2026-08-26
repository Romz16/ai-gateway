# System context
```mermaid
flowchart LR
    Client[Client application] -->|Bearer key / HTTPS| Gateway[AI Gateway]
    Operator[Operator] -->|Policy and catalog| Gateway
    Gateway --> OpenAI
    Gateway --> Anthropic
    Gateway --> Gemini
    Gateway --> Ollama
    Gateway --> Fake[Fake provider / local demo]
    Gateway --> Monitoring[Metrics and traces]
```
