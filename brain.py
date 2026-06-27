import threading
from datetime import datetime
from db import (
    save_message, load_recent_messages,
    get_user_profile, load_setting, save_setting
)
from memory import search_similar_memories, save_embedding, should_store_memory
from llm import chat_completion, CURRENT_MODEL, CURRENT_PROVIDER
from search import web_search

class Brain:
    def __init__(self):
        self.conversation_history = load_recent_messages(20)
        self.conversation_summary = ""
        self.pending_topic = None

    def classify_query(self, text):
        text = text.lower()
        if any(x in text for x in ["who won", "latest", "news", "today", "score"]):
            return "FACTUAL"
        if any(x in text for x in ["remember", "you said", "last time", "earlier"]):
            return "MEMORY"
        if any(x in text for x in ["hi", "hello", "how are you", "hey"]):
            return "CASUAL"
        return "GENERAL"

    def respond(self, user_input, on_reply, on_error):
        """
        on_reply: callback function that receives the reply string
        on_error: callback function that receives the error string
        """
        self.conversation_history.append({
            "role": "user",
            "content": user_input
        })
        threading.Thread(
            target=self._generate,
            args=(user_input, on_reply, on_error)
        ).start()

    def _generate(self, user_message, on_reply, on_error):
        try:
            query_type = self.classify_query(user_message)
            use_memory = query_type in ["MEMORY", "GENERAL"]
            use_search = query_type == "FACTUAL" and bool(load_setting("web_search_api_key", ""))

            semantic_memories = search_similar_memories(user_message) if use_memory else []
            recent_history = load_recent_messages(6)
            search_results = web_search(user_message) if use_search else None

            system_prompt = self._build_prompt(
                query_type, search_results, recent_history, semantic_memories
            )

            messages = [{"role": "system", "content": system_prompt}]
            if self.conversation_summary:
                messages.append({
                    "role": "system",
                    "content": f"Summary: {self.conversation_summary}"
                })
            messages += self.conversation_history[-8:]

            reply = chat_completion(model=CURRENT_MODEL, messages=messages)

            self.conversation_history.append({
                "role": "assistant",
                "content": reply
            })

            self._maybe_extract_profile()
            self._maybe_summarize()

            on_reply(reply)

        except Exception as e:
            on_error(str(e))

    def _build_prompt(self, query_type, search_results, recent_history, semantic_memories):
        prompt = """
You are a personal companion. Calm, direct, genuine.
- No bullet points in casual conversation
- Never ask more than one question at a time
- Match the user's energy
- Keep responses short unless detail is requested
- Never say "Great!", "Certainly!", "Of course!"
"""
        prompt += f"\nCurrent time: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"

        if search_results:
            prompt += f"\nWeb results:\n{search_results}\n"
        elif query_type == "FACTUAL":
            prompt += "\nNo web search available. Say so if uncertain.\n"

        user_profile = get_user_profile()
        if user_profile:
            prompt += f"\nUser background (use naturally):\n{user_profile}\n"

        prompt += "\nRecent conversation:\n"
        for m in recent_history:
            prompt += f"{m['role']}: {m['content']}\n"

        prompt += "\nRelevant memories:\n"
        for m in semantic_memories:
            prompt += f"{m['role']}: {m['text']}\n"

        return prompt

    def _maybe_extract_profile(self):
        if len(self.conversation_history) % 8 == 0:
            from llm import extract_and_save_profile
            snippet = self.conversation_history[-8:]
            snippet_text = "\n".join([f"{m['role']}: {m['content']}" for m in snippet])
            threading.Thread(target=extract_and_save_profile, args=(snippet_text,)).start()

    def _maybe_summarize(self):
        if len(self.conversation_history) > 20:
            summary_prompt = f"Summarize briefly:\n{self.conversation_history[:-10]}"
            self.conversation_summary = chat_completion(
                model=CURRENT_MODEL,
                messages=[{"role": "user", "content": summary_prompt}]
            )
            self.conversation_history = self.conversation_history[-10:]
