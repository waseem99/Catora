from fastapi import FastAPI

from catora_api.api.git_publishing import router as git_publishing_router


def register_git_publishing_router(app: FastAPI) -> None:
    app.include_router(git_publishing_router)
