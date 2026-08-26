"""Inject a local primary-provider outage, verify fallback, then restore it."""

import json
import subprocess
import time

import httpx


def compose(*args):
    return subprocess.run(
        ["docker", "compose", *args], check=True, capture_output=True, text=True
    ).stdout


def main():
    key = compose("exec", "-T", "gateway", "cat", "/srv/secrets/demo-api-key").strip()
    try:
        compose(
            "-f",
            "docker-compose.yml",
            "-f",
            "docker/chaos.yml",
            "up",
            "-d",
            "--force-recreate",
            "fake-provider",
        )
        with httpx.Client(
            base_url="http://localhost:8000", headers={"Authorization": "Bearer " + key}, timeout=10
        ) as client:
            # Startup is bounded. This script never contacts paid providers.
            for _ in range(20):
                response = client.post(
                    "/v1/generate",
                    json={
                        "task": "classification",
                        "messages": [{"role": "user", "content": "A great service."}],
                        "constraints": {"allowed_providers": ["fake", "fake_backup"]},
                    },
                )
                if response.status_code == 200 and response.json()["provider"] == "fake_backup":
                    break
                time.sleep(0.25)
            response.raise_for_status()
            assert response.json()["fallback_used"]
            print(
                json.dumps(
                    {
                        "fallback_verified": True,
                        "provider": response.json()["provider"],
                        "provider_status": client.get("/v1/providers/status").json(),
                    },
                    indent=2,
                )
            )
    finally:
        compose("up", "-d", "--force-recreate", "fake-provider")


if __name__ == "__main__":
    main()
