# Memory for a larger model

![Qwen3 14B managing SHADOW 50M as its memory: six facts stored one call each, five recalled with the record quoted, a missing order reported missing](shadow_memory.gif)

A large model talks; SHADOW keeps what it is told, on disk, and hands it back when asked. Two tools, `remember` and
`recall`, offered as an MCP server so any client that speaks MCP can use them, and used here by Qwen3 14B through an
Ollama tool-calling loop. The large model's own context is cut to three turns; what it stored earlier it gets back from
SHADOW, with the record quoted. Nothing leaves the machine.

    python examples/memory_mcp/shadow_memory_mcp.py --store ~/shadow_memory                      # stdio MCP server
    python examples/memory_mcp/agent.py --model qwen3:14b --store ~/shadow_memory                # a chat, Qwen managing the memory
    python examples/memory_mcp/agent.py --model qwen3:14b --store ~/shadow_memory --script session.txt --keep 3

The agent needs Ollama with a model that calls tools. Each `remember` appends one line to `records.txt` in the store and
rebuilds the archive from it (0.4 ms a token). Each `recall` runs the question through SHADOW against that archive and
returns the answer, the record it read with its position, and the fetch stats; a question about something never stored
comes back as "no record". Driven through the Python MCP client (initialize, two remembers, three recalls) the whole
exchange took 3.2 s on a laptop.

## What the session shows

Ten turns, scripted so the run is repeatable (`session.txt` in the recording). Qwen3 14B, temperature 0:

| turn | what Qwen did | what SHADOW returned |
|---|---|---|
| "My name is Sai and I live in Sydney" | two `remember` calls, one fact each | stored |
| "a dog called Bruno, allergic to peanuts" | two calls, the allergy under `condition` | stored |
| "Order 4471 shipped to Dublin, 12 items" | two calls | stored |
| "What is 27 + 45?" | answered itself, no call | |
| "Where do I live?" | `recall` city of User A1 | Sydney, record quoted |
| "What is my dog called?" | `recall` dog of User A1 | Bruno, record quoted |
| "Where was order 4471 shipped to?" | `recall` destination of Order 4471 | Dublin, record quoted |
| "What am I allergic to?" | `recall` condition of User A1 | peanut allergy, record quoted |
| "status of order 9999?" | `recall` | no record of Order 9999 |

Five of five recalls right, the absent order reported absent, with three turns of context in the large model. The same
script with gpt-oss 20B gave the same result; qwen2.5 7B did not manage the tools (it merged facts into one record and
sometimes wrote the word "recall" instead of calling it).

## The shape of a record

SHADOW finds a record by an identifier and an attribute word, so the tool description asks for one fact per call in the
form `<Identifier> <attribute>: <value>.`, with the person in the conversation as `User A1`. Measured through the kernel
with six attributes under one identifier and three candidate records into attention:

| identifier | attributes recalled |
|---|---|
| `User A1` | 6 of 6 |
| `User` | 5 of 6 (the health record answered from general knowledge instead) |
| `User-1`, `Person A1` | 5 of 6 (name confused with another attribute) |

Three candidates instead of one matters when many attributes share one key: 5 of 6 against 2 to 4 of 6 with one. Health
facts go under `condition`; "allergy" as the attribute word was answered from general knowledge in the direct test.

## Files

- `shadow_memory_mcp.py`: the MCP server, and the `Store` class the agent imports (records file, rebuild, recall).
- `agent.py`: the Ollama loop; `--keep` sets how many turns the large model keeps, `--script` replays a session.
- `shadow_memory.gif`: the run above, as it printed.
