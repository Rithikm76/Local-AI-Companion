import sqlite3
import os

# Clear database
conn = sqlite3.connect("chatbot_memory.db")
conn.execute("DELETE FROM messages")
conn.execute("DELETE FROM user_profile")
conn.execute("UPDATE settings SET value='llama3.1:8b' WHERE key='current_model'")
conn.commit()
conn.close()

# Delete FAISS index
if os.path.exists("memory.index"):
    os.remove("memory.index")

print("Done. Fresh start.")