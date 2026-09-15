"""A larger model manages SHADOW as its long-term memory: a tool-calling loop through Ollama, the same two tools the MCP server offers.

    python examples/memory_mcp/agent.py --model qwen3:14b --store ~/shadow_memory
    python examples/memory_mcp/agent.py --model qwen3:14b --store ~/shadow_memory --script session.txt   # lines to send, then quit

The big model talks; when something is worth keeping it calls remember, and when it needs something it calls recall.
SHADOW keeps the records on disk and answers with the record quoted. The big model's context can be short; the memory
is not in it. Needs Ollama running with a model that supports tools.
"""
import argparse, json, pathlib, sys
import requests
if hasattr(sys.stdout, "reconfigure"): sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = pathlib.Path(__file__).resolve().parent; sys.path.insert(0, str(HERE))
from shadow_memory_mcp import Store

TOOLS = [
    {"type": "function", "function": {"name": "remember", "description": "Store one fact in long-term memory on disk. Write it as one line with an identifier and an attribute word, like 'User A1 city: Sydney.' or 'Order 4471 status: shipped.'",
                                      "parameters": {"type": "object", "properties": {"fact": {"type": "string"}}, "required": ["fact"]}}},
    {"type": "function", "function": {"name": "recall", "description": "Ask long-term memory a question naming the identifier and the attribute, like 'What is the city of User A1?'. Returns the answer with the record it came from, or 'no record'.",
                                      "parameters": {"type": "object", "properties": {"question": {"type": "string"}}, "required": ["question"]}}},
]
SYSTEM = ("You are an assistant whose long-term memory is kept by a separate small model on disk, reached only through the tools remember and recall. "
          "Your own context is short and gets cleared, so you cannot rely on it.\n"
          "Rules:\n"
          "1. When the user states a fact, call remember ONCE PER FACT, each as one line '<Identifier> <attribute>: <value>.' with a single attribute. "
          "Facts about the person you are talking to use the identifier 'User A1'. Examples: 'User A1 name: Sai.' 'User A1 city: Sydney.' 'User A1 dog: Bruno.' "
          "'User A1 condition: peanut allergy.' 'Order 4471 destination: Dublin.' 'Order 4471 items: 12.' Health facts go under the attribute 'condition'.\n"
          "2. When the user asks about anything that could have been stored, you MUST call the recall tool (never write the word recall as text) with a "
          "question 'What is the <attribute> of <Identifier>?', for example 'What is the dog of User A1?' or 'What is the destination of Order 4471?', "
          "then answer from the tool result in one sentence and mention the record it quoted. If the tool says there is no record, say so.\n"
          "3. Arithmetic and general questions you answer yourself. Keep replies to one or two sentences.")


def chat(host, model, messages):
    r = requests.post(f"{host}/api/chat", json={"model": model, "messages": messages, "tools": TOOLS, "stream": False, "options": {"temperature": 0}}, timeout=600)
    r.raise_for_status(); return r.json()["message"]


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--model", default="qwen3:14b"); ap.add_argument("--store", default="~/shadow_memory")
    ap.add_argument("--host", default="http://localhost:11434"); ap.add_argument("--script", default=None); ap.add_argument("--keep", type=int, default=6, help="turns the big model keeps in its own context")
    a = ap.parse_args(); store = Store(a.store); history = []
    lines = [l.rstrip("\n") for l in open(a.script, encoding="utf-8")] if a.script else None
    print(f"{a.model} with SHADOW memory at {store.dir}. 'quit' to stop.")
    while True:
        if lines is not None:
            if not lines: break
            q = lines.pop(0); print(f"you> {q}")
        else:
            try: q = input("you> ").strip()
            except EOFError: break
        if q in ("quit", "exit"): break
        if not q: continue
        history.append({"role": "user", "content": q}); history = history[-2 * a.keep:]
        for _ in range(4):                                                  # a turn may take a few tool calls
            msg = chat(a.host, a.model, [{"role": "system", "content": SYSTEM}] + history); history.append(msg)
            calls = msg.get("tool_calls") or []
            if not calls: break
            for c in calls:
                fn = c["function"]["name"]; args = c["function"].get("arguments") or {}
                if isinstance(args, str): args = json.loads(args)
                out = store.remember(args.get("fact", "")) if fn == "remember" else store.recall(args.get("question", "")) if fn == "recall" else "unknown tool"
                print(f"   [{fn}({json.dumps(args, ensure_ascii=False)})] -> {out.splitlines()[0]}")
                history.append({"role": "tool", "content": out})
        print(f"{a.model.split(':')[0]}> {history[-1].get('content', '').strip()}")


if __name__ == "__main__": main()
