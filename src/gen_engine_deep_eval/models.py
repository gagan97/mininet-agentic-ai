from typing import Any

from pydantic.v1 import BaseModel


class GenerativeEngineResponse(BaseModel):
    session_id: str
    type: str
    content: str
    metadata: dict[str, Any]
