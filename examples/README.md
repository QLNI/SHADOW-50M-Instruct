# Harnesses

What the model is for, built around what it measures well, each with a recording of a real session and its numbers.

| harness | what it shows | folder |
|---|---|---|
| Video memory | a vision model watches a film once, SHADOW remembers every moment on disk and answers by moment, time or content | [video_memory/](video_memory/) |
| Records desk | an inventory or a log becomes memory on disk; ask by identifier, get the record quoted, offline, in 42 MB | [records_desk/](records_desk/) |
| Draft model | SHADOW proposes tokens for Qwen3-32B in llama.cpp, which keeps the ones it would have chosen; 19.7 to 28.5 tokens a second on one GPU | [draft/](draft/) |
| Memory for a larger model | an MCP server with remember and recall; Qwen3 14B stores facts one call each and gets them back with the record quoted | [memory_mcp/](memory_mcp/) |

Every number in these folders was measured through the shipped kernel on the shipped container: one fresh process per
question for the memory harnesses, the kernel's server mode (one process, answers identical to the one-shot kernel on 30 of
30 prompts) for the draft.
