from pydantic import BaseModel, ConfigDict, Field


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = Field(default="healthy", description="Service health status")
    service: str = Field(default="nexora-backend", description="Service identifier")
