from __future__ import annotations

from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, ValidationError, field_validator

from src.classifier import HEALTH_MODEL_NAME, ReturnReasonClassifier
from src.schema import ClassificationResult

BASE_DIR = Path(__file__).resolve().parents[1]
UI_PATH = BASE_DIR / "ui" / "index.html"


class ClassificationRequest(BaseModel):
    text: str
    language: Literal["en", "ar", "auto"] = "auto"

    @field_validator("text")
    @classmethod
    def validate_text(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("Text must not be empty.")
        if len(value) > 500:
            raise ValueError("Text must be 500 characters or fewer.")
        return value


app = FastAPI(title="MumzReturn AI", version="1.0.0")
classifier = ReturnReasonClassifier()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    messages: list[str] = []
    for error in exc.errors():
        message = error.get("msg", "Invalid request.")
        if message.startswith("Value error, "):
            message = message.replace("Value error, ", "", 1)
        messages.append(message)
    detail = " ".join(dict.fromkeys(messages)) or "Invalid request."
    return JSONResponse(status_code=422, content={"detail": detail})


@app.get("/", include_in_schema=False)
async def root() -> FileResponse:
    return FileResponse(UI_PATH)


@app.get("/favicon.ico", include_in_schema=False)
async def favicon() -> Response:
    return Response(status_code=204)


@app.get("/health")
async def health() -> dict[str, object]:
    return {
        "status": "ok",
        "model": HEALTH_MODEL_NAME,
        "fallback_mode": classifier.fallback_mode,
    }


@app.post("/classify", response_model=ClassificationResult)
async def classify_return(payload: ClassificationRequest) -> ClassificationResult:
    try:
        run = classifier.classify_with_metadata(text=payload.text, language=payload.language)
        return ClassificationResult.model_validate(run.result)
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Classifier returned invalid schema: {exc.errors()}",
        ) from exc
