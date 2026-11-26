"""Codoh: Abdoh's coding assistant page (ABDOH_EPIC_9.md, section 3.1).

A chat about the code in one folder, run by Claude Code (the user's Claude plan) or by the
user's ChatGPT plan with Codoh's own tools. Nothing of Abdoh's (its prompt, actions, memory,
conversations) goes to the coding models, and nothing of Codoh's goes to Abdoh.
"""

# How Codoh may act, the same words for both engines (claude.py and chatgpt.py map them).
MODES = ("ask", "auto_edit", "plan", "full")
DEFAULT_MODE = "ask"
EFFORTS = ("low", "medium", "high", "xhigh", "max")
ENGINES = ("claude", "chatgpt")
