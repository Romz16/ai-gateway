from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings

from app.core.errors import ProviderError
from app.domain.models import GenerationRequest, ModelSpec
from app.providers.fake import FakeProvider


class Faults(BaseSettings):
    fake_provider_failure_rate: float = Field(0, ge=0, le=1)
    fake_provider_timeout_rate: float = Field(0, ge=0, le=1)
    fake_provider_invalid_output_rate: float = Field(0, ge=0, le=1)
    fake_provider_latency_ms: float = Field(10, ge=0, le=10000)


class Payload(BaseModel):
    request: GenerationRequest
    model: str


app = FastAPI(title="Fake provider: local demonstration only")
faults = Faults()
provider = FakeProvider(
    faults.fake_provider_failure_rate,
    faults.fake_provider_timeout_rate,
    faults.fake_provider_invalid_output_rate,
    faults.fake_provider_latency_ms,
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/generate")
async def generate(payload: Payload):  # type: ignore[no-untyped-def]
    model = ModelSpec(
        provider="fake",
        model=payload.model,
        input_per_million=0,
        output_per_million=0,
        quality=3,
        expected_latency_ms=10,
        tasks=[],
        effective_from="2026-08-26",
        pricing_note="Synthetic",
    )
    try:
        return await provider.generate(payload.request, model)
    except ProviderError:
        return JSONResponse({"error": "Injected provider failure"}, status_code=503)
