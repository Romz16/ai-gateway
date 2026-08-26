# Technical references

Provider wire adapters were checked against these official API references on 26 August 2026:

- [OpenAI Chat Completions](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)
- [Anthropic Messages](https://platform.claude.com/docs/en/api/messages/create)
- [Gemini generateContent](https://ai.google.dev/api/generate-content)
- [Ollama chat](https://docs.ollama.com/api/chat)
- [OWASP Top 10 for LLM applications](https://genai.owasp.org/llm-top-10/)

The OpenAI adapter uses Chat Completions for a small common text contract. It disables storage and applies an output token cap. JSON mode is followed by local schema validation. The domain does not depend on the OpenAI SDK.

No external model identifier or vendor price is claimed to be current in the demo catalog. Replace the external example placeholders with account-specific, reviewed values. Contract tests use recorded synthetic HTTP shapes; they are not live provider certification.
