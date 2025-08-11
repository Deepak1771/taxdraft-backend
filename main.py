import io
from typing import Optional
from fastapi import FastAPI, Header, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from openpyxl import Workbook

API_KEY = "CHANGE_ME"  # set a real secret later

app = FastAPI(title="SD Tax Engine", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
from fastapi import FastAPI

app = FastAPI(title="Tax Draft Backend", version="1.0.0")

@app.get("/")
def root():
    return {"status": "ok", "message": "Tax Draft Backend is running"}

def check_key(x_api_key: Optional[str]):
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")

class PingOut(BaseModel):
    message: str = "pong"

@app.get("/ping", response_model=PingOut)
def ping(): return {"message": "pong"}

@app.post("/compute")
def compute(x_api_key: Optional[str] = Header(None)):
    check_key(x_api_key)
    # dummy response just to prove it works
    return {"total_income": 123456, "tax": 7890}

@app.post("/excel")
def excel(x_api_key: Optional[str] = Header(None)):
    check_key(x_api_key)
    # tiny demo Excel so you can test file download
    wb = Workbook(); ws = wb.active; ws.title = "Hello"
    ws["A1"] = "It works!"
    buf = io.BytesIO(); wb.save(buf); buf.seek(0)
    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="demo.xlsx"'}
    )

