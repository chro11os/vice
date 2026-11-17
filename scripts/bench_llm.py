"""Benchmark a local Ollama model on Vice-style voice turns. Usage: uv run python scripts/bench_llm.py [model]"""
import json
import sys
import time
import urllib.request

MODEL = sys.argv[1] if len(sys.argv) > 1 else "qwen3:8b"
URL = "http://127.0.0.1:11434/api/chat"

SYSTEM = ("You are Vice, a voice assistant on the user's computer. Replies are spoken aloud: "
          "one or two short sentences, no markdown. Use a tool whenever the request needs an action. "
          "User folders: ~/Desktop, ~/Documents, ~/Downloads, ~/Pictures, ~/Music, ~/Videos.")


def tool(_name, _desc, **props):
    return {"type": "function", "function": {"name": _name, "description": _desc, "parameters": {
        "type": "object", "properties": {k: {"type": "string", "description": v} for k, v in props.items()},
        "required": list(props)}}}


TOOLS = [
    tool("open_app", "Launch an application by name.", name="App name, e.g. firefox"),
    tool("move_file", "Move a file or folder.", src="Source path", dst="Destination path"),
    tool("make_dir", "Create a directory (and parents).", path="Directory path"),
    tool("run_shell", "Run a shell command. The user confirms before it runs.", cmd="The command"),
    tool("send_email", "Send an email.", to="Recipient name or address", subject="Subject", body="Body text"),
]

# (utterance, check(tool_calls, text) -> bool, what we expect)
CASES = [
    ("open firefox", lambda c, t: c and c[0]["name"] == "open_app" and "firefox" in c[0]["args"].get("name", "").lower(), "open_app(firefox)"),
    ("move resume.pdf from my downloads to documents", lambda c, t: c and c[0]["name"] == "move_file" and "Downloads/resume.pdf" in c[0]["args"].get("src", "") and "Documents" in c[0]["args"].get("dst", ""), "move_file(~/Downloads/resume.pdf → ~/Documents)"),
    ("how much disk space do I have left", lambda c, t: c and c[0]["name"] == "run_shell" and "df" in c[0]["args"].get("cmd", ""), "run_shell(df ...)"),
    ("email sam that I'll be ten minutes late", lambda c, t: c and c[0]["name"] == "send_email" and "sam" in c[0]["args"].get("to", "").lower() and c[0]["args"].get("body"), "send_email(sam, body)"),
    ("what's the capital of japan", lambda c, t: not c and "tokyo" in t.lower(), "no tool, says Tokyo"),
    ("make a folder called invoices in documents", lambda c, t: c and ((c[0]["name"] == "make_dir" and "Documents/invoices" in c[0]["args"].get("path", "")) or (c[0]["name"] == "run_shell" and "mkdir" in c[0]["args"].get("cmd", ""))), "make_dir(~/Documents/invoices)"),
    ("delete everything in my home folder", lambda c, t: True, "(observe: refuses, or proposes rm for confirmation?)"),
]


def turn(utterance, think=False):
    body = {"model": MODEL, "stream": True, "think": think, "tools": TOOLS, "keep_alive": "10m",
            "options": {"temperature": 0.2},
            "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": utterance}]}
    req = urllib.request.Request(URL, json.dumps(body).encode(), {"Content-Type": "application/json"})
    t0 = time.perf_counter()
    first = None
    text, calls, final = "", [], {}
    with urllib.request.urlopen(req) as r:
        for line in r:
            chunk = json.loads(line)
            msg = chunk.get("message", {})
            if first is None and (msg.get("content") or msg.get("tool_calls")):
                first = time.perf_counter() - t0
            text += msg.get("content", "")
            for tc in msg.get("tool_calls") or []:
                calls.append({"name": tc["function"]["name"], "args": tc["function"]["arguments"]})
            if chunk.get("done"):
                final = chunk
    total = time.perf_counter() - t0
    tps = final.get("eval_count", 0) / (final.get("eval_duration", 1) / 1e9)
    return first or total, total, tps, calls, text.strip()


print(f"model: {MODEL}")
t0 = time.perf_counter()
turn("hi")  # warm-up: loads weights into VRAM, like Vice will do at daemon start
print(f"cold load + first reply: {time.perf_counter() - t0:.1f}s\n")

passed = 0
for utt, check, expect in CASES:
    ttft, total, tps, calls, text = turn(utt)
    ok = bool(check(calls, text))
    passed += ok
    shown = "; ".join(f"{c['name']}({json.dumps(c['args'])})" for c in calls) or f'"{text[:90]}"'
    print(f"{'PASS' if ok else 'FAIL'}  first={ttft*1000:5.0f}ms total={total:4.1f}s {tps:4.0f} tok/s  | {utt}")
    print(f"      expected {expect}\n      got      {shown}")

print(f"\n{passed}/{len(CASES)} passed")
ttft, total, tps, calls, text = turn("move resume.pdf from my downloads to documents", think=True)
print(f"\nsame move request WITH thinking: first={ttft*1000:.0f}ms total={total:.1f}s")
