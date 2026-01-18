from pydantic import BaseModel, Field

class IntentResolution(BaseModel):
    intent: str = Field(
        description="One of: SOP_QUERY, TROUBLESHOOTING, DATA_ENGINEERING"
    )
