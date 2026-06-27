import faiss
import numpy as np
import os
from sentence_transformers import SentenceTransformer

# =============================
# EMBEDDING MODEL
# =============================

print("Loading embedding model...")
embedding_model = SentenceTransformer("all-MiniLM-L6-v2")
EMBEDDING_DIM = 384
print("Embedding model ready")

index = faiss.IndexFlatL2(EMBEDDING_DIM)
vector_id_map = []


# =============================
# SAVE EMBEDDING
# =============================

def save_embedding(text, message_id):
    embedding = embedding_model.encode([text])[0]
    vector = np.array([embedding]).astype("float32")
    index.add(vector)
    vector_id_map.append(message_id)


# =============================
# SEARCH
# =============================

def search_similar_memories(query, limit=3):
    if index.ntotal == 0:
        return []

    query_embedding = embedding_model.encode([query])[0]
    query_vector = np.array([query_embedding]).astype("float32")

    distances, indices = index.search(query_vector, limit)

    from db import DB_NAME
    import sqlite3

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    results = []
    for idx in indices[0]:
        if idx == -1:
            continue
        message_id = vector_id_map[idx]
        cursor.execute(
            "SELECT role, content FROM messages WHERE id=?",
            (message_id,)
        )
        row = cursor.fetchone()
        if row:
            results.append({"role": row[0], "text": row[1]})

    conn.close()
    return results


# =============================
# PERSIST INDEX
# =============================

def save_index():
    faiss.write_index(index, "memory.index")


def rebuild_faiss_index():
    global index

    from db import DB_NAME
    import sqlite3

    if os.path.exists("memory.index"):
        index = faiss.read_index("memory.index")

        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("SELECT id, content FROM messages")
        rows = cursor.fetchall()
        conn.close()

        for message_id, text in rows:
            if _should_store_memory(text):
                vector_id_map.append(message_id)

        print(f"FAISS index loaded. Vectors: {index.ntotal}")

    else:
        print("Rebuilding index from database...")

        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("SELECT id, content FROM messages")
        rows = cursor.fetchall()
        conn.close()

        for message_id, text in rows:
            if _should_store_memory(text):
                embedding = embedding_model.encode([text])[0]
                vector = np.array([embedding]).astype("float32")
                index.add(vector)
                vector_id_map.append(message_id)

        print(f"FAISS index rebuilt. Vectors: {index.ntotal}")


# =============================
# PRIVATE HELPER
# =============================

def _should_store_memory(text):
    text = text.lower().strip()
    if len(text.split()) < 4:
        return False
    trivial = ["hello", "hi", "ok", "thanks", "fine", "good"]
    if text in trivial:
        return False
    return True
