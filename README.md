# Local AI Companion

An AI assistant that runs entirely on your machine and learns who you are over time.

All conversations, memories, and your personal profile stay local. Nothing leaves your device.

## What it does

- Remembers past conversations across sessions using semantic search (FAISS)
- Builds a personal profile from your conversations over time
- Runs fully offline using Ollama, or switches to Groq cloud for better model quality
- Searches the web when needed using Tavily
- Switches between models from a settings panel
- Detects internet connectivity and adjusts behavior accordingly

## Requirements

- Python 3.10+
- [Ollama](https://ollama.com) installed
- A free [Groq API key](https://console.groq.com) — optional, for cloud mode
- A free [Tavily API key](https://tavily.com) — optional, for web search

## Setup
```bash
git clone https://github.com/yourusername/local-ai-companion.git
cd local-ai-companion
pip install -r requirements.txt
ollama pull llama3.1:8b
python chatbot_gui.py
```

## Status

Early development. Core memory, user profiling, web search, and model switching are functional. Desktop widget UI is planned next.

## License

MIT
