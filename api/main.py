from dotenv import load_dotenv
import sys, os

from langchain.messages import HumanMessage

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
load_dotenv()

from graph.graph import app as graph_name
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel


app = FastAPI(title="Capstone App")

class ReqModel(BaseModel):
    query: str
    thread_id: str = "default"


class RespModel(BaseModel):
    answer: str | None = None


@app.post("/trigger",response_model=RespModel)
async def trigger(req:ReqModel):
    try:
        query = req.query
        thread_id = req.thread_id

        config = {"configurable":{"thread_id":thread_id}}
        response=graph_name.invoke({
            "question":query

        },config)

        return RespModel(answer= str(response.get("answer","")))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# if __name__ == "__main__":
#     query = "If an entity YAML has an unknown top-level field like foo: bar next to spec/metadata, does it get silently dropped, ignored, or rejected — and by whom?"
#     config = {"configurable": {"thread_id": "test_123"}}
#     response = app.invoke({"question": query}, config)
