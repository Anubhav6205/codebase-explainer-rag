from langchain_text_splitters import MarkdownHeaderTextSplitter
from fastembed import SparseTextEmbedding
from pathlib import Path
from qdrant_client import QdrantClient,models
from dotenv import load_dotenv
import os
load_dotenv()
# Initializing the markdown splitter

headers_to_split_on = [
    ("#","Header 1"),
    ("##","Header 2"),
    ("###","Header 3")
]


markdown_splitter = MarkdownHeaderTextSplitter(headers_to_split_on)

print("Markdown splitter:",markdown_splitter)


# Accumulating docs

backstage_dir = Path(__file__).parent.parent.parent/"backstage"
md_files = backstage_dir.rglob('*.md')
markdown_documents = []

print("Backstage dir:",backstage_dir)
print("md files:",md_files)

# Iterating thorugh the files and pushing to list

for index,md_file in enumerate(md_files):
    text = Path.read_text(md_file,encoding="utf-8")
    chunks = markdown_splitter.split_text(text)
    rel_path = str(md_file.relative_to(backstage_dir)).replace("\\", "/")
    for chunk in chunks:
        chunk.metadata["source_file"] = rel_path
    markdown_documents.extend(chunks)
    print("Chunks:",index,chunks)


qdrant_secret = os.getenv("QDRANT_API_KEY")
quadrant_client = QdrantClient(url="https://e83b0b74-3a98-4cdd-85f0-5cbb042fdfed.us-east-1-1.aws.cloud.qdrant.io",
                      api_key=qdrant_secret)




# creating a sparse-only collection

quadrant_client.create_collection(
    collection_name="sparse_docs",
    vectors_config={},
    sparse_vectors_config={
        "sparse": models.SparseVectorParams()
    }
)


# initializing sparse embedding model
sparse_model = SparseTextEmbedding(model_name="Qdrant/bm25")


# converting chunks to sparse embeddings
texts = [chunk.page_content for chunk in markdown_documents]
sparse_embeddings = list(sparse_model.embed(texts))

# BATCH_SIZE = 400
# sparse_embeddings = []
# for i in range(0, len(texts), BATCH_SIZE):
#     batch = texts[i:i + BATCH_SIZE]
#     batch_embeddings = list(sparse_model.embed(batch,batch_size=16))
#     sparse_embeddings.extend(batch_embeddings)
#     print(f"Embedded {min(i + BATCH_SIZE, len(texts))}/{len(texts)}")



# ingesting the embeddings in db

points = [
    models.PointStruct(
        id=i,
        vector={
            "sparse": models.SparseVector(
                indices=sparse_embeddings[i].indices.tolist(),
                values=sparse_embeddings[i].values.tolist()
            )
        },
        payload={"text": texts[i], **markdown_documents[i].metadata}
    )
    for i in range(len(texts))
]

UPSERT_BATCH = 200
for i in range(0, len(points), UPSERT_BATCH):
    quadrant_client.upsert(collection_name="sparse_docs", points=points[i:i + UPSERT_BATCH])
    print(f"Upserted {min(i + UPSERT_BATCH, len(points))}/{len(points)}")