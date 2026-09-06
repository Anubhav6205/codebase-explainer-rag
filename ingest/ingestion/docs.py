from langchain_text_splitters import MarkdownHeaderTextSplitter
from pathlib import Path
from qdrant_client import QdrantClient,models
from dotenv import load_dotenv
import voyageai
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

backstage_dir = Path(__file__).parent.parent/"backstage"
md_files = backstage_dir.rglob('*.md')
markdown_documents = []

print("Backstage dir:",backstage_dir)
print("md files:",md_files)

# Iterating thorugh the files and pushing to list

for index,md_file in enumerate(md_files):
    text = Path.read_text(md_file,encoding="utf-8")
    chunks = markdown_splitter.split_text(text)
    markdown_documents.extend(chunks)
    print("Chunks:",index,chunks)


qdrant_secret = os.getenv("QDRANT_API_KEY")
quadrant_client = QdrantClient(url="https://e83b0b74-3a98-4cdd-85f0-5cbb042fdfed.us-east-1-1.aws.cloud.qdrant.io",
                      api_key=qdrant_secret)




# creating a collection

quadrant_client.create_collection(collection_name="capstone_4",vectors_config=models.VectorParams(size=1024,distance=models.Distance.COSINE))




voyage_secret = os.getenv("VOYAGE_API_KEY")
vo=voyageai.Client(api_key=voyage_secret)



# converting chunks to embeddings
texts = [chunk.page_content for chunk in markdown_documents]
result = vo.embed(texts,model="voyage-code-3",input_type="document")
embeddings = result.embeddings



# Query → embed query → search Qdrant → get nearest points → read payload → return text to user

# ingesting the embeddings in db

points = [models.PointStruct(id=i,vector=embeddings[i],payload={"text":texts[i],**markdown_documents[i].metadata}) for i in range(len(texts))]


quadrant_client.upsert(collection_name="capstone_3",points=points)