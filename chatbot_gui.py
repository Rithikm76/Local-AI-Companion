import ollama
import sqlite3
import faiss
import numpy as np
import tkinter as tk
from tkinter import scrolledtext, ttk
from datetime import datetime
import threading
import requests
import os
import subprocess
from sentence_transformers import SentenceTransformer

try:
    from groq import Groq
    GROQ_AVAILABLE = True
except ImportError:
    GROQ_AVAILABLE = False

print("Starting chatbot...")

# =============================
# MODEL CONFIGURATION
# =============================

PROVIDERS = {
    "ollama": {
        "label": "Ollama (Local)",
        "models": {
            "Llama 3.1 (8B)": "llama3.1:8b",
            "Llama 3.2 (3B)": "llama3.2",
            "Mistral (7B)": "mistral:7b",
        }
    },
    "groq": {
        "label": "Groq (Cloud)",
        "models": {
            "Llama 3.3 70B": "llama-3.3-70b-versatile",
            "Llama 3.1 8B": "llama-3.1-8b-instant",
            "Mixtral 8x7B": "mixtral-8x7b-32768",
            "Gemma 2 9B": "gemma2-9b-it",
        }
    }
}

CURRENT_PROVIDER = "ollama"
CURRENT_MODEL = "llama3.1:8b"

# =============================
# EMBEDDING + VECTOR SYSTEM
# =============================

print("Loading embedding model...")
embedding_model = SentenceTransformer("all-MiniLM-L6-v2")
EMBEDDING_DIM = 384
print("Embedding model ready")

index = faiss.IndexFlatL2(EMBEDDING_DIM)
vector_id_map = []

DB_NAME = "chatbot_memory.db"

# =============================
# DATABASE SETUP
# =============================

def setup_database():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS messages(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        role TEXT,
        content TEXT,
        timestamp TEXT
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS user_profile(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        trait TEXT,
        value TEXT,
        confidence REAL DEFAULT 0.5,
        timestamp TEXT
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS settings(
        key TEXT PRIMARY KEY,
        value TEXT
    )
    """)

    conn.commit()
    conn.close()


# =============================
# SETTINGS
# =============================

def save_setting(key, value):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
    INSERT OR REPLACE INTO settings (key, value)
    VALUES (?, ?)
    """, (key, value))
    conn.commit()
    conn.close()


def load_setting(key, default=None):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key=?", (key,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return row[0]
    return default


# =============================
# CHAT COMPLETION ABSTRACTION
# =============================

def chat_completion(model, messages, provider=None):
    if provider is None:
        provider = CURRENT_PROVIDER

    if provider == "groq":
        api_key = load_setting("groq_api_key", "")
        if not api_key:
            return "[Error] Groq API key not set. Open Settings to enter your key."

        client = Groq(api_key=api_key)
        response = client.chat.completions.create(
            model=model,
            messages=messages
        )
        return response.choices[0].message.content

    else:
        response = ollama.chat(
            model=model,
            messages=messages
        )
        return response["message"]["content"]


# =============================
# MEMORY STORAGE
# =============================

def should_store_memory(text):
    text = text.lower().strip()

    if len(text.split()) < 4:
        return False

    trivial = ["hello", "hi", "ok", "thanks", "fine", "good"]

    if text in trivial:
        return False

    return True


def save_message(role, content):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cursor.execute(
        "INSERT INTO messages(role, content, timestamp) VALUES(?,?,?)",
        (role, content, timestamp)
    )

    message_id = cursor.lastrowid
    conn.commit()
    conn.close()

    if should_store_memory(content):
        threading.Thread(
            target=save_embedding,
            args=(content, message_id)
        ).start()


def save_embedding(text, message_id):
    embedding = embedding_model.encode([text])[0]
    vector = np.array([embedding]).astype("float32")

    index.add(vector)
    vector_id_map.append(message_id)


# =============================
# USER PROFILE
# =============================

def extract_and_save_profile(conversation_snippet):
    prompt = f"""
Read the following conversation and extract any facts about the user.

Only extract clear, specific facts. Examples:
- interests or hobbies
- what they are studying or working on
- preferences about how they like to communicate
- personal details they mentioned

Return each fact on a separate line in this exact format:
trait: value

If there are no clear facts, return: none

Conversation:
{conversation_snippet}
"""

    output = chat_completion(
        model=CURRENT_MODEL,
        messages=[{"role": "user", "content": prompt}]
    )

    output = output.strip()

    if output.lower() == "none":
        return

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for line in output.splitlines():

        if ":" not in line:
            continue

        parts = line.split(":", 1)

        if len(parts) != 2:
            continue

        trait = parts[0].strip().lower()
        value = parts[1].strip()

        if not trait or not value:
            continue

        cursor.execute("""
        SELECT id FROM user_profile
        WHERE trait = ? AND value = ?
        """, (trait, value))

        existing = cursor.fetchone()

        if existing:
            cursor.execute("""
            UPDATE user_profile
            SET confidence = MIN(confidence + 0.1, 1.0),
                timestamp = ?
            WHERE trait = ? AND value = ?
            """, (timestamp, trait, value))
        else:
            cursor.execute("""
            INSERT INTO user_profile (trait, value, confidence, timestamp)
            VALUES (?, ?, ?, ?)
            """, (trait, value, 0.5, timestamp))

    conn.commit()
    conn.close()


def get_user_profile():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("""
    SELECT trait, value FROM user_profile
    ORDER BY confidence DESC, timestamp DESC
    """)

    rows = cursor.fetchall()
    conn.close()

    if not rows:
        return None

    profile_text = ""
    for trait, value in rows:
        profile_text += f"- {trait}: {value}\n"

    return profile_text


# =============================
# SEMANTIC SEARCH
# =============================

def search_similar_memories(query, limit=3):
    if index.ntotal == 0:
        return []

    query_embedding = embedding_model.encode([query])[0]
    query_vector = np.array([query_embedding]).astype("float32")

    distances, indices = index.search(query_vector, limit)

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
            results.append({
                "role": row[0],
                "text": row[1]
            })

    conn.close()

    return results


# =============================
# LOAD RECENT CHAT HISTORY
# =============================

def load_recent_messages(limit=20):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("""
    SELECT role, content
    FROM messages
    ORDER BY id DESC
    LIMIT ?
    """, (limit,))

    rows = cursor.fetchall()
    rows.reverse()

    conn.close()

    messages = []

    for role, content in rows:
        messages.append({
            "role": role,
            "content": content
        })

    return messages


# =============================
# REBUILD FAISS INDEX
# =============================

def rebuild_faiss_index():
    global index

    if os.path.exists("memory.index"):
        index = faiss.read_index("memory.index")

        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("SELECT id, content FROM messages")
        rows = cursor.fetchall()
        conn.close()

        for message_id, text in rows:
            if should_store_memory(text):
                vector_id_map.append(message_id)

        print(f"FAISS index loaded from disk. Vectors: {index.ntotal}")

    else:
        print("No saved index found, rebuilding from database...")

        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("SELECT id, content FROM messages")
        rows = cursor.fetchall()
        conn.close()

        for message_id, text in rows:
            if should_store_memory(text):
                embedding = embedding_model.encode([text])[0]
                vector = np.array([embedding]).astype("float32")
                index.add(vector)
                vector_id_map.append(message_id)

        print(f"FAISS index rebuilt. Vectors: {index.ntotal}")


# =============================
# CONNECTIVITY CHECK
# =============================

def is_online():
    try:
        requests.get("https://www.google.com", timeout=3)
        return True
    except Exception:
        return False


# =============================
# WEB SEARCH
# =============================

def web_search(query):
    api_key = load_setting("web_search_api_key", "")
    if not api_key:
        return None

    try:
        url = "https://serpapi.com/search"
        params = {
            "q": query,
            "api_key": api_key
        }
        response = requests.get(url, params=params, timeout=5)
        results = response.json()

        if "organic_results" in results:
            search_text = ""
            for result in results["organic_results"][:3]:
                title = result.get("title", "")
                snippet = result.get("snippet", "")
                search_text += f"- {title}: {snippet}\n"
            return search_text if search_text else None

        return None

    except Exception:
        return None


# =============================
# ENSURE MODEL EXISTS (OLLAMA)
# =============================

def ensure_model(model_name):
    try:
        subprocess.run(
            ["ollama", "pull", model_name],
            capture_output=True
        )
    except Exception as e:
        print(f"Could not pull model {model_name}: {e}")


def get_available_local_models():
    try:
        result = subprocess.run(
            ["ollama", "list"],
            capture_output=True,
            text=True
        )
        return result.stdout.lower()
    except Exception:
        return ""


# =============================
# CHATBOT GUI
# =============================

class ChatbotGUI:

    def __init__(self, root):

        global CURRENT_MODEL, CURRENT_PROVIDER

        self.root = root
        self.root.title("AI Assistant")
        self.root.geometry("800x600")

        self.bg = "#1e1e1e"
        self.root.configure(bg=self.bg)

        # Load saved provider
        saved_provider = load_setting("current_provider", "ollama")
        if saved_provider in PROVIDERS:
            CURRENT_PROVIDER = saved_provider

        # Load saved model
        saved_model = load_setting("current_model")
        if saved_model:
            if CURRENT_PROVIDER == "ollama":
                try:
                    available_local = get_available_local_models()
                    model_base = saved_model.split(":")[0]
                    if model_base in available_local:
                        CURRENT_MODEL = saved_model
                    else:
                        print(f"Saved model {saved_model} not found locally, falling back to default.")
                        save_setting("current_model", "llama3.1:8b")
                except Exception:
                    pass
            elif CURRENT_PROVIDER == "groq":
                CURRENT_MODEL = saved_model

        self.conversation_history = load_recent_messages(20)
        self.conversation_summary = ""
        self.pending_topic = None

        # --- Top bar ---
        top_bar = tk.Frame(root, bg="#2a2a2a")
        top_bar.pack(fill=tk.X, padx=0, pady=0)

        tk.Label(
            top_bar,
            text="AI Assistant",
            bg="#2a2a2a",
            fg="white",
            font=("Arial", 11, "bold")
        ).pack(side=tk.LEFT, padx=10, pady=5)

        provider_label_text = PROVIDERS[CURRENT_PROVIDER]["label"]
        self.model_label = tk.Label(
            top_bar,
            text=f"{provider_label_text}  ·  {CURRENT_MODEL}",
            bg="#2a2a2a",
            fg="#888888",
            font=("Arial", 9)
        )
        self.model_label.pack(side=tk.LEFT, padx=10, pady=5)

        provider_color = "#44ff88" if CURRENT_PROVIDER == "ollama" else "#00b4d8"
        self.provider_dot = tk.Label(
            top_bar,
            text="●",
            bg="#2a2a2a",
            fg=provider_color,
            font=("Arial", 9)
        )
        self.provider_dot.pack(side=tk.LEFT, padx=0, pady=5)

        settings_btn = tk.Button(
            top_bar,
            text="⚙ Settings",
            command=self.open_settings,
            bg="#2a2a2a",
            fg="white",
            font=("Arial", 9),
            borderwidth=0,
            cursor="hand2"
        )
        settings_btn.pack(side=tk.RIGHT, padx=10, pady=5)

        # --- Chat display ---
        self.chat_display = scrolledtext.ScrolledText(
            root,
            wrap=tk.WORD,
            bg=self.bg,
            fg="white",
            font=("Arial", 11),
            state=tk.DISABLED
        )
        self.chat_display.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # --- Input area ---
        self.input_box = tk.Text(
            root,
            height=3,
            bg="#2d2d2d",
            fg="white",
            insertbackground="white"
        )
        self.input_box.pack(fill=tk.X, padx=10)
        self.input_box.bind("<Return>", self.send_message_event)

        self.send_button = tk.Button(
            root,
            text="Send",
            command=self.send_message
        )
        self.send_button.pack(pady=5)

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)


    def update_top_bar(self):
        provider_label_text = PROVIDERS[CURRENT_PROVIDER]["label"]
        self.model_label.config(text=f"{provider_label_text}  ·  {CURRENT_MODEL}")

        provider_color = "#44ff88" if CURRENT_PROVIDER == "ollama" else "#00b4d8"
        self.provider_dot.config(fg=provider_color)


    def open_settings(self):

        settings_win = tk.Toplevel(self.root)
        settings_win.title("Settings")
        settings_win.geometry("400x460")
        settings_win.configure(bg="#1e1e1e")
        settings_win.resizable(False, False)

        # --- Provider selection ---
        tk.Label(
            settings_win,
            text="Provider",
            bg="#1e1e1e",
            fg="white",
            font=("Arial", 11, "bold")
        ).pack(pady=(15, 5))

        provider_var = tk.StringVar()
        provider_labels = {pid: pdata["label"] for pid, pdata in PROVIDERS.items()}
        provider_ids = {pdata["label"]: pid for pid, pdata in PROVIDERS.items()}
        provider_var.set(PROVIDERS[CURRENT_PROVIDER]["label"])

        provider_dropdown = ttk.Combobox(
            settings_win,
            textvariable=provider_var,
            values=list(provider_labels.values()),
            state="readonly",
            width=30
        )
        provider_dropdown.pack(pady=5)

        # --- Groq API Key ---
        api_frame = tk.Frame(settings_win, bg="#1e1e1e")
        api_frame.pack(fill=tk.X, padx=30, pady=5)

        tk.Label(
            api_frame,
            text="Groq API Key",
            bg="#1e1e1e",
            fg="#aaaaaa",
            font=("Arial", 9)
        ).pack(anchor=tk.W)

        saved_api_key = load_setting("groq_api_key", "")
        api_key_var = tk.StringVar(value=saved_api_key)
        api_key_entry = tk.Entry(
            api_frame,
            textvariable=api_key_var,
            width=40,
            bg="#2d2d2d",
            fg="white",
            insertbackground="white",
            show="•"
        )
        api_key_entry.pack(pady=2)

        show_key_var = tk.BooleanVar(value=False)

        def toggle_key_visibility():
            api_key_entry.config(show="" if show_key_var.get() else "•")

        tk.Checkbutton(
            api_frame,
            text="Show key",
            variable=show_key_var,
            command=toggle_key_visibility,
            bg="#1e1e1e",
            fg="#888888",
            selectcolor="#2d2d2d",
            activebackground="#1e1e1e",
            activeforeground="#888888",
            font=("Arial", 8)
        ).pack(anchor=tk.W)

        tk.Label(
            api_frame,
            text="Get a free key at console.groq.com",
            bg="#1e1e1e",
            fg="#666666",
            font=("Arial", 8),
            cursor="hand2"
        ).pack(anchor=tk.W)

        # --- Web Search API Key ---
        search_frame = tk.Frame(settings_win, bg="#1e1e1e")
        search_frame.pack(fill=tk.X, padx=30, pady=5)

        tk.Label(
            search_frame,
            text="Web Search API Key (SerpAPI)",
            bg="#1e1e1e",
            fg="#aaaaaa",
            font=("Arial", 9)
        ).pack(anchor=tk.W)

        saved_search_key = load_setting("web_search_api_key", "")
        search_key_var = tk.StringVar(value=saved_search_key)
        search_key_entry = tk.Entry(
            search_frame,
            textvariable=search_key_var,
            width=40,
            bg="#2d2d2d",
            fg="white",
            insertbackground="white",
            show="•"
        )
        search_key_entry.pack(pady=2)

        show_search_key_var = tk.BooleanVar(value=False)

        def toggle_search_key_visibility():
            search_key_entry.config(show="" if show_search_key_var.get() else "•")

        tk.Checkbutton(
            search_frame,
            text="Show key",
            variable=show_search_key_var,
            command=toggle_search_key_visibility,
            bg="#1e1e1e",
            fg="#888888",
            selectcolor="#2d2d2d",
            activebackground="#1e1e1e",
            activeforeground="#888888",
            font=("Arial", 8)
        ).pack(anchor=tk.W)

        tk.Label(
            search_frame,
            text="Get a free key at serpapi.com",
            bg="#1e1e1e",
            fg="#666666",
            font=("Arial", 8),
            cursor="hand2"
        ).pack(anchor=tk.W)

        # --- Model selection ---
        tk.Label(
            settings_win,
            text="Model",
            bg="#1e1e1e",
            fg="white",
            font=("Arial", 11, "bold")
        ).pack(pady=(10, 5))

        model_var = tk.StringVar()

        model_dropdown = ttk.Combobox(
            settings_win,
            textvariable=model_var,
            state="readonly",
            width=30
        )
        model_dropdown.pack(pady=5)

        status_label = tk.Label(
            settings_win,
            text="",
            bg="#1e1e1e",
            fg="#888888",
            font=("Arial", 9)
        )
        status_label.pack(pady=2)

        def refresh_models(*args):
            selected_provider_label = provider_var.get()
            selected_provider_id = provider_ids[selected_provider_label]
            models = PROVIDERS[selected_provider_id]["models"]
            model_names = list(models.keys())
            model_dropdown["values"] = model_names

            current_label = model_names[0] if model_names else ""
            for label, mid in models.items():
                if mid == CURRENT_MODEL:
                    current_label = label
                    break
            model_var.set(current_label)

            if selected_provider_id == "groq":
                api_frame.pack(fill=tk.X, padx=30, pady=5)
                if not GROQ_AVAILABLE:
                    status_label.config(
                        text="⚠ groq package not installed. Run: pip install groq",
                        fg="#ff4444"
                    )
                elif not api_key_var.get().strip():
                    status_label.config(
                        text="⚠ API key required for Groq models",
                        fg="#ffaa00"
                    )
                else:
                    status_label.config(text="✓ API key set", fg="#44ff88")
            else:
                api_frame.pack_forget()
                check_ollama_model_status()

        def check_ollama_model_status(*args):
            selected_provider_label = provider_var.get()
            selected_provider_id = provider_ids[selected_provider_label]

            if selected_provider_id != "ollama":
                return

            selected_label = model_var.get()
            if not selected_label:
                return

            models = PROVIDERS["ollama"]["models"]
            if selected_label not in models:
                return

            selected_model = models[selected_label]
            available_local = get_available_local_models()

            if any(
                selected_model.split(":")[0] in line
                for line in available_local.splitlines()
            ):
                status_label.config(text="✓ Model available locally", fg="#44ff88")
            else:
                status_label.config(text="⚠ Not downloaded. Will pull on apply.", fg="#ffaa00")

        provider_dropdown.bind("<<ComboboxSelected>>", refresh_models)
        model_dropdown.bind("<<ComboboxSelected>>", check_ollama_model_status)

        refresh_models()

        def apply_settings():
            global CURRENT_MODEL, CURRENT_PROVIDER

            selected_provider_label = provider_var.get()
            selected_provider_id = provider_ids[selected_provider_label]
            selected_label = model_var.get()
            models = PROVIDERS[selected_provider_id]["models"]

            if selected_label not in models:
                status_label.config(text="⚠ Select a model first", fg="#ff4444")
                return

            selected_model = models[selected_label]

            # Save search key regardless of provider
            search_key = search_key_var.get().strip()
            if search_key:
                save_setting("web_search_api_key", search_key)

            # Handle provider logic
            if selected_provider_id == "groq":
                key = api_key_var.get().strip()
                if not key:
                    status_label.config(
                        text="⚠ Enter your Groq API key first",
                        fg="#ff4444"
                    )
                    return
                if not GROQ_AVAILABLE:
                    status_label.config(
                        text="⚠ groq package not installed",
                        fg="#ff4444"
                    )
                    return
                save_setting("groq_api_key", key)
                CURRENT_PROVIDER = selected_provider_id
                CURRENT_MODEL = selected_model
                save_setting("current_provider", CURRENT_PROVIDER)
                save_setting("current_model", CURRENT_MODEL)
                print(f"Switched to Groq model: {CURRENT_MODEL}")
                status_label.config(text="✓ Groq model set successfully", fg="#44ff88")
                self.update_top_bar()
                settings_win.after(1500, settings_win.destroy)

            elif selected_provider_id == "ollama":
                available_local = get_available_local_models()
                model_base = selected_model.split(":")[0]
                is_available = any(
                    model_base in line
                    for line in available_local.splitlines()
                )

                if is_available:
                    CURRENT_PROVIDER = selected_provider_id
                    CURRENT_MODEL = selected_model
                    save_setting("current_provider", CURRENT_PROVIDER)
                    save_setting("current_model", CURRENT_MODEL)
                    print(f"Switched to Ollama model: {CURRENT_MODEL}")
                    status_label.config(text="✓ Model switched successfully", fg="#44ff88")
                    self.update_top_bar()
                    settings_win.after(1500, settings_win.destroy)
                else:
                    status_label.config(
                        text="Downloading model... this may take a while",
                        fg="#ffaa00"
                    )
                    apply_btn.config(state=tk.DISABLED)

                    def pull_then_switch():
                        ensure_model(selected_model)
                        global CURRENT_MODEL, CURRENT_PROVIDER
                        CURRENT_PROVIDER = selected_provider_id
                        CURRENT_MODEL = selected_model
                        save_setting("current_provider", CURRENT_PROVIDER)
                        save_setting("current_model", CURRENT_MODEL)
                        print(f"Model pulled and switched to: {CURRENT_MODEL}")
                        settings_win.after(0, lambda: status_label.config(
                            text="✓ Download complete. Model switched.",
                            fg="#44ff88"
                        ))
                        self.root.after(0, self.update_top_bar)
                        settings_win.after(2000, settings_win.destroy)

                    threading.Thread(target=pull_then_switch).start()

        apply_btn = tk.Button(
            settings_win,
            text="Apply",
            command=apply_settings,
            bg="#0084ff",
            fg="white",
            font=("Arial", 10),
            borderwidth=0,
            padx=20,
            cursor="hand2"
        )
        apply_btn.pack(pady=15)


    def on_close(self):
        faiss.write_index(index, "memory.index")
        self.root.destroy()


    def display_message(self, role, content, save=True):
        self.chat_display.config(state=tk.NORMAL)

        timestamp = datetime.now().strftime("%H:%M")

        if role == "user":
            self.chat_display.insert(tk.END, f"\n{timestamp} You: {content}\n")
        else:
            self.chat_display.insert(tk.END, f"\n{timestamp} Bot: {content}\n")

        self.chat_display.config(state=tk.DISABLED)
        self.chat_display.see(tk.END)

        if save:
            save_message(role, content)


    def replace_thinking_message(self, reply):
        self.chat_display.config(state=tk.NORMAL)
        self.chat_display.delete("end-3l", "end-1l")

        timestamp = datetime.now().strftime("%H:%M")
        self.chat_display.insert(tk.END, f"\n{timestamp} Bot: {reply}\n")

        self.chat_display.config(state=tk.DISABLED)
        self.chat_display.see(tk.END)

        save_message("assistant", reply)


    def send_message_event(self, event):
        self.send_message()
        return "break"


    def send_message(self):
        user_input = self.input_box.get("1.0", tk.END).strip()

        if user_input.lower() in ["yes", "yeah", "yep", "ok", "sure", "continue"]:
            if self.pending_topic:
                user_input = f"Continue explaining this topic: {self.pending_topic}"

        if not user_input:
            return

        self.input_box.delete("1.0", tk.END)

        self.display_message("user", user_input)
        self.display_message("assistant", "Thinking...", save=False)

        self.conversation_history.append({
            "role": "user",
            "content": user_input
        })

        self.send_button.config(state=tk.DISABLED)

        threading.Thread(target=self.generate_response).start()


    def classify_query(self, text):
        text = text.lower()

        if any(x in text for x in ["who won", "latest", "news", "today", "score", "match", "result"]):
            return "FACTUAL"

        if any(x in text for x in ["remember", "you said", "last time", "earlier", "previously"]):
            return "MEMORY"

        if any(x in text for x in ["hi", "hello", "how are you", "what's up", "hey"]):
            return "CASUAL"

        return "GENERAL"


    def generate_response(self):

        try:
            user_message = self.conversation_history[-1]["content"]
            query_type = self.classify_query(user_message)

            use_memory = query_type in ["MEMORY", "GENERAL"]
            use_search = query_type == "FACTUAL" and bool(load_setting("web_search_api_key", ""))

            semantic_memories = []
            if use_memory:
                semantic_memories = search_similar_memories(user_message)

            recent_history = load_recent_messages(6)

            search_results = None
            if use_search:
                search_results = web_search(user_message)

            # =============================
            # SYSTEM PROMPT
            # =============================

            system_prompt = """
You are a personal companion. Not an assistant, not a customer service bot.

You have a personality. You are calm, direct, and genuine.

CONVERSATION RULES:
- Never use bullet points or numbered lists in casual conversation
- Never ask more than one question at a time
- Match the user's energy — if they're casual, be casual
- Keep responses short unless the user clearly wants detail
- Don't end every message with a question
- Don't offer help menus or structured roadmaps unless explicitly asked
- If the user shares something personal, acknowledge it naturally like a person would
- Never say things like "Great to know!" or "Certainly!" or "Of course!"

MEMORY RULES:
- Use what you know about the user naturally, don't announce it
- Don't let past context dominate if the user has clearly moved to a new topic
- If you don't know something about the user, just have a normal conversation
- Use profile knowledge as background context only, not as the topic of conversation
"""

            current_time = datetime.now().strftime("%Y-%m-%d %H:%M")
            system_prompt += f"\nCurrent system time: {current_time}\n"

            if search_results:
                system_prompt += f"\nWeb search results (use these to answer factual questions):\n{search_results}\n"
            elif query_type == "FACTUAL":
                system_prompt += "\nNo web search available. If you are uncertain about a fact, say so clearly instead of guessing.\n"

            user_profile = get_user_profile()
            if user_profile:
                system_prompt += f"\nBackground context about the user (use naturally, do not force into conversation):\n{user_profile}\n"

            system_prompt += "\nRecent conversation:\n"
            if recent_history:
                for m in recent_history:
                    system_prompt += f"{m['role']}: {m['content']}\n"
            else:
                system_prompt += "None\n"

            system_prompt += "\nRelevant past memories:\n"
            if semantic_memories:
                for m in semantic_memories:
                    system_prompt += f"{m['role']}: {m['text']}\n"
            else:
                system_prompt += "None\n"

            # =============================
            # BUILD MESSAGE LIST
            # =============================

            messages = [{"role": "system", "content": system_prompt}]

            if self.conversation_summary:
                messages.append({
                    "role": "system",
                    "content": f"Conversation summary: {self.conversation_summary}"
                })

            messages += self.conversation_history[-8:]

            # =============================
            # MODEL CALL
            # =============================

            reply = chat_completion(
                model=CURRENT_MODEL,
                messages=messages
            )

            if len(reply.split()) > 8:
                self.pending_topic = user_message

            print("Model reply:", reply)

            # =============================
            # SAVE RESPONSE
            # =============================

            self.conversation_history.append({
                "role": "assistant",
                "content": reply
            })

            if len(self.conversation_history) % 8 == 0:
                snippet = self.conversation_history[-8:]
                snippet_text = "\n".join([f"{m['role']}: {m['content']}" for m in snippet])
                threading.Thread(
                    target=extract_and_save_profile,
                    args=(snippet_text,)
                ).start()

            if len(self.conversation_history) > 20:
                summary_prompt = f"""
Summarize the following conversation briefly:

{self.conversation_history[:-10]}
"""
                self.conversation_summary = chat_completion(
                    model=CURRENT_MODEL,
                    messages=[{"role": "user", "content": summary_prompt}]
                )
                self.conversation_history = self.conversation_history[-10:]

            self.root.after(0, self.replace_thinking_message, reply)

        except Exception as e:
            self.root.after(
                0,
                self.display_message,
                "assistant",
                f"Error: {str(e)}"
            )

        finally:
            self.root.after(
                0,
                lambda: self.send_button.config(state=tk.NORMAL)
            )


# =============================
# MAIN
# =============================

if __name__ == "__main__":

    setup_database()
    rebuild_faiss_index()

    root = tk.Tk()
    app = ChatbotGUI(root)

    root.mainloop()
