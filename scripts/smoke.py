"""HTTP smoke test for a running demo gateway. Never prints the API key."""

import argparse
import json
import os
from pathlib import Path

import httpx


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--key-file")
    args = parser.parse_args()
    key = (
        Path(args.key_file).read_text().strip() if args.key_file else os.environ["GATEWAY_API_KEY"]
    )
    with httpx.Client(
        base_url=args.url, headers={"Authorization": "Bearer " + key}, timeout=10
    ) as client:
        assert client.get("/ready").status_code == 200
        payload = {
            "task": "classification",
            "messages": [{"role": "user", "content": "A great service."}],
            "constraints": {"allowed_providers": ["fake", "fake_backup"]},
        }
        first = client.post("/v1/generate", json=payload, headers={"Idempotency-Key": "smoke-v1"})
        first.raise_for_status()
        assert first.json()["content"] == "positive"
        replay = client.post("/v1/generate", json=payload, headers={"Idempotency-Key": "smoke-v1"})
        assert replay.json() == first.json()
        payload["response_schema"] = {
            "type": "object",
            "properties": {"category": {"type": "string", "const": "general"}},
            "required": ["category"],
        }
        structured = client.post("/v1/generate/structured", json=payload)
        structured.raise_for_status()
        assert structured.json()["content"] == {"category": "general"}
        assert client.get("/v1/usage?tenant=another-tenant").status_code == 403
        assert (
            client.post(
                "/v1/generate", json=payload, headers={"Authorization": "Bearer invalid"}
            ).status_code
            == 401
        )
        print(
            json.dumps(
                {
                    "ready": True,
                    "generation": True,
                    "structured": True,
                    "idempotency": True,
                    "tenant_isolation": True,
                    "invalid_key_rejected": True,
                    "trace_id": first.json()["trace_id"],
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
