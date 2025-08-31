# websub_server.py
from fastapi import FastAPI, Response, Query

app = FastAPI()

@app.get("/websub/callback")
def verify(
    hub_mode: str | None = Query(None, alias="hub.mode"),
    hub_topic: str | None = Query(None, alias="hub.topic"),
    hub_challenge: str = Query("", alias="hub.challenge"),
    hub_lease_seconds: int | None = Query(None, alias="hub.lease_seconds"),
):
    # 必须原样回显 challenge，纯文本
    return Response(content=hub_challenge, media_type="text/plain")
