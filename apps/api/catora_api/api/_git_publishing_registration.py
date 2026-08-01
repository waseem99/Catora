from fastapi import FastAPI

from catora_api.api.git_publishing import router


def register_git_publishing(app: FastAPI) -> None:
    app.include_router(router)
