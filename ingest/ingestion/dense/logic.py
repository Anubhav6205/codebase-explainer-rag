from llama_index.core.node_parser import CodeSplitter
from llama_index.core import Document
from pathlib import Path
from qdrant_client import QdrantClient,models
from dotenv import load_dotenv
import voyageai
import os
load_dotenv()
# Initializing the code splitter



code_splitter = CodeSplitter(
    language="typescript",
    chunk_lines=80,
    chunk_lines_overlap=15,
    max_chars=3000
)

print("Code splitter:",code_splitter)



# Accumulating docs

backstage_dir = Path(__file__).parent.parent.parent/"backstage"
ts_files = [
    f for f in backstage_dir.rglob('*')
    if f.suffix in ('.ts', '.tsx')
    and not f.name.endswith('.d.ts')
]
code_documents = []

print("Backstage dir:",backstage_dir)
print("ts files:",ts_files)

# Iterating thorugh the files and pushing to list

for index,ts_file in enumerate(ts_files):
    text = ts_file.read_text(encoding="utf-8")
    rel_path = str(ts_file.relative_to(backstage_dir)).replace("\\", "/")
    nodes = code_splitter.get_nodes_from_documents([Document(text=text, metadata={"source_file": rel_path})])
    code_documents.extend(nodes)
    print("Chunks:",index,nodes)


qdrant_secret = os.getenv("QDRANT_API_KEY")
quadrant_client = QdrantClient(url="https://e83b0b74-3a98-4cdd-85f0-5cbb042fdfed.us-east-1-1.aws.cloud.qdrant.io",
                      api_key=qdrant_secret)





# creating a collection

quadrant_client.create_collection(collection_name="dense_logic",vectors_config=models.VectorParams(size=1024,distance=models.Distance.COSINE))




voyage_secret = os.getenv("VOYAGE_API_KEY")
vo=voyageai.Client(api_key=voyage_secret)



# converting chunks to embeddings
texts = [chunk.text for chunk in code_documents]

BATCH_SIZE = 400
embeddings = []
for i in range(0, len(texts), BATCH_SIZE):
    batch = texts[i:i + BATCH_SIZE]
    result = vo.embed(batch, model="voyage-code-3", input_type="document")
    embeddings.extend(result.embeddings)
    print(f"Embedded {min(i + BATCH_SIZE, len(texts))}/{len(texts)}")



# Query → embed query → search Qdrant → get nearest points → read payload → return text to user

# ingesting the embeddings in db

points = [models.PointStruct(id=i,vector=embeddings[i],payload={"text":texts[i],**code_documents[i].metadata}) for i in range(len(texts))]


UPSERT_BATCH = 15
for i in range(0, len(points), UPSERT_BATCH):
    quadrant_client.upsert(collection_name="dense_logic", points=points[i:i + UPSERT_BATCH])
    print(f"Upserted {min(i + UPSERT_BATCH, len(points))}/{len(points)}")