from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.api.deps import ApiKeyProjectDep, SessionDep
from app.services import ingest as ingest_service
from app.services.ingest import IngestBatch

router = APIRouter(prefix="/v1", tags=["sdk"])


class IngestResult(BaseModel):
    traces: int
    spans: int


@router.post("/ingest", response_model=IngestResult, status_code=status.HTTP_202_ACCEPTED)
async def ingest(
    batch: IngestBatch, project: ApiKeyProjectDep, session: SessionDep
) -> IngestResult:
    """Upsert a batch of traces and spans for the API key's project."""
    try:
        await ingest_service.ingest(session, project.id, batch)
    except ingest_service.ForeignIdError as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "A trace or span id is already used by another project."
        ) from exc
    return IngestResult(traces=len(batch.traces), spans=len(batch.spans))
