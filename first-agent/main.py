import subprocess
import json
import re
import sys
from typing import Any

from ollama import chat

RESET = "\033[0m"
DIM = "\033[2m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
MAGENTA = "\033[35m"


def fmt_thinking(text: str) -> str:
    abbreviated = text[:80] + "..." if len(text) > 80 else text
    return f"{DIM}[Thinking...]{RESET} {abbreviated}"


def fmt_tool_call(name: str, args: dict) -> str:
    args_str = json.dumps(args, indent=2)[1:-1]
    return f"{CYAN}◇ {MAGENTA}{name}{RESET}({args_str})"


def fmt_tool_result(result: list[dict]) -> str:
    lines = []
    for r in result:
        if "error" in r:
            lines.append(f"  {YELLOW}✗{RESET} {r['host']}: {r['error']}")
        else:
            loss = r.get("packet_loss", 0)
            loss_str = f"{loss}% loss" if loss > 0 else "0% loss"
            lines.append(
                f"  {GREEN}✓{RESET} {r['host']}: {r['rtt_avg']:.1f}ms avg "
                f"(min={r['rtt_min']:.1f}, max={r['rtt_max']:.1f}), {loss_str}"
            )
    return "\n".join(lines)


def run_ping(host: str) -> dict[str, Any]:
    try:
        result = subprocess.run(
            ["ping", "-c", "5", host], text=True, stderr=subprocess.STDOUT, stdout=subprocess.PIPE
        )
        output = result.stdout
        match = re.search(r"round-trip.*=\s*([\d.]+)/([\d.]+)/([\d.]+)", output)
        if match:
            return {
                "host": host,
                "rtt_min": float(match.group(1)),
                "rtt_avg": float(match.group(2)),
                "rtt_max": float(match.group(3)),
                "packet_loss": 0.0 if "0%" in output else float(output.split("%")[0].split()[-1]),
            }
        return {"host": host, "error": output}
    except Exception as e:
        return {"host": host, "error": str(e)}


def ping(hosts: list[str]) -> list[dict[str, Any]]:
    results = []
    for host in hosts:
        results.append(run_ping(host))
    return results


tools = [ping]


messages: list[dict[str, Any]] = [
    {
        "role": "system",
        "content": "Present findings concisely. Use brief bullet points or sections. No markdown formatting unless requested.",
    }
]


def run_agent():
    while True:
        stream = chat(
            model="qwen3:4b",
            messages=messages,
            tools=tools,
            stream=True,
        )

        thinking = ""
        content = ""
        tool_calls = []

        for chunk in stream:
            if chunk.message.thinking:
                thinking += chunk.message.thinking
            if chunk.message.content:
                content += chunk.message.content
            if chunk.message.tool_calls:
                tool_calls.extend(chunk.message.tool_calls)

        if thinking:
            print(fmt_thinking(thinking))

        if content:
            print(content, end="", flush=True)

        messages.append(
            {
                "role": "assistant",
                "thinking": thinking,
                "content": content,
                "tool_calls": tool_calls,
            }
        )

        if not tool_calls:
            print()
            break

        for call in tool_calls:
            print()
            if call.function.name == "ping":
                result = ping(**call.function.arguments)
                print(fmt_tool_call(call.function.name, call.function.arguments))
                print(fmt_tool_result(result))
                messages.append(
                    {"role": "tool", "tool_name": call.function.name, "content": json.dumps(result)}
                )
            else:
                print(fmt_tool_call(call.function.name, call.function.arguments))
                error_result = [{"host": call.function.name, "error": "Unknown tool"}]
                print(fmt_tool_result(error_result))
                messages.append(
                    {
                        "role": "tool",
                        "tool_name": call.function.name,
                        "content": json.dumps(error_result),
                    }
                )

        print()


if __name__ == "__main__":
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        print(f"{CYAN}➜ {line}{RESET}")
        messages.append({"role": "user", "content": line})
        run_agent()
        print(f"{DIM}---{RESET}")
