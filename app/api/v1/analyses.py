from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from app.db.persistence import save_analysis
from app.db.session import get_session
from app.schemas.analysis import AnalyzeRequest, AnalyzeResponse
from app.services.exceptions import AIProviderConfigError, TodoAnalyzerError
from app.services.todo_analyzer import TodoAnalyzer


router = APIRouter(prefix="/analyses", tags=["analyses"])
analyzer = TodoAnalyzer()


@router.post("", response_model=AnalyzeResponse)
async def create_analysis(
    request: AnalyzeRequest, session: Session = Depends(get_session)
) -> AnalyzeResponse:
    try:
        response = await analyzer.analyze(request)
    except AIProviderConfigError as exc:
        raise HTTPException(
            status_code=500,
            detail={"code": exc.code, "message": exc.message},
        ) from exc
    except TodoAnalyzerError as exc:
        raise HTTPException(
            status_code=502,
            detail={"code": exc.code, "message": exc.message},
        ) from exc

    save_analysis(session, request, response)
    return response
