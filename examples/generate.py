"""Set GATEWAY_API_KEY before running this example."""

import asyncio
import os

import httpx


async def main():
    async with httpx.AsyncClient(
        base_url=os.getenv("GATEWAY_URL", "http://localhost:8000"),
        headers={"Authorization": "Bearer " + os.environ["GATEWAY_API_KEY"]},
        timeout=10,
    ) as client:
        response = await client.post(
            "/v1/generate",
            json={
                "task": "summarization",
                "messages": [
                    {
                        "role": "user",
                        "content": "The gateway provides one API for several model providers.",
                    }
                ],
                "constraints": {
                    "quality": "balanced",
                    "max_cost_usd": "0.01",
                    "max_latency_ms": 5000,
                },
            },
        )
        response.raise_for_status()
        print(response.json())


if __name__ == "__main__":
    asyncio.run(main())
