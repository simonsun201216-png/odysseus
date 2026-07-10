import os
from pathlib import Path
from fastapi import APIRouter, HTTPException, Request

CASES_DIR = Path(__file__).parent.parent / "prophetis_research" / "cases"

def setup_cases_routes():
    router = APIRouter(prefix="/api/cases", tags=["cases"])

    @router.get("/")
    def list_cases(request: Request):
        if not CASES_DIR.exists():
            return []
        
        cases = []
        for item in CASES_DIR.iterdir():
            if item.is_dir():
                files = [f.name for f in item.iterdir() if f.is_file()]
                cases.append({
                    "id": item.name,
                    "name": item.name,
                    "files": files
                })
        return cases

    @router.get("/{case_id}/{file_name}")
    def get_case_file(request: Request, case_id: str, file_name: str):
        file_path = CASES_DIR / case_id / file_name
        if not file_path.exists() or not file_path.is_file():
            raise HTTPException(status_code=404, detail="File not found")
        
        try:
            content = file_path.read_text(encoding="utf-8")
            return {"content": content, "type": file_path.suffix}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    return router
