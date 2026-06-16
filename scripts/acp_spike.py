"""Phase-0 spike: prove AgenticOps can drive claude-agent-acp over stdio JSON-RPC + Bedrock.

Run manually:  .venv/bin/python scripts/acp_spike.py "say hello in one word"
NOT a test. Prints the raw protocol exchange so we can pin: handshake, protocol
version, session/update shapes, and whether Bedrock pass-through works.
"""
import asyncio
import json
import os
import sys


async def main(prompt: str) -> int:
    # Reuse the safe-env recipe from mcp_manager (HOME/PATH/etc + AWS creds for Bedrock).
    from mcp.client.stdio import get_default_environment
    env = get_default_environment()
    for key in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN",
                "AWS_REGION", "AWS_DEFAULT_REGION", "AWS_PROFILE",
                "AWS_SHARED_CREDENTIALS_FILE", "AWS_CONFIG_FILE",
                "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI", "AWS_CONTAINER_AUTHORIZATION_TOKEN"):
        v = os.environ.get(key)
        if v:
            env[key] = v
    env["CLAUDE_CODE_USE_BEDROCK"] = "1"          # route the agent through Bedrock
    env.setdefault("AWS_REGION", "us-east-1")

    # NOTE (spike finding): `-y` is REQUIRED — without it npx blocks on an
    # install-confirmation prompt and `initialize` never gets a response.
    print(">>> launching: npx -y @agentclientprotocol/claude-agent-acp", file=sys.stderr)
    proc = await asyncio.create_subprocess_exec(
        "npx", "-y", "@agentclientprotocol/claude-agent-acp",
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE, env=env,
    )

    next_id = [0]
    def send(method, params):
        next_id[0] += 1
        msg = {"jsonrpc": "2.0", "id": next_id[0], "method": method, "params": params}
        line = (json.dumps(msg) + "\n").encode()
        print(f"--> {method} {json.dumps(params)[:200]}", file=sys.stderr)
        proc.stdin.write(line)
        return next_id[0]

    def notify(method, params):
        msg = {"jsonrpc": "2.0", "method": method, "params": params}
        proc.stdin.write((json.dumps(msg) + "\n").encode())

    async def read_until(pred, label, timeout=60):
        # Print every line; return the first JSON object matching pred.
        while True:
            raw = await asyncio.wait_for(proc.stdout.readline(), timeout)
            if not raw:
                raise RuntimeError(f"agent closed stdout while waiting for {label}")
            line = raw.decode().strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                print(f"<-- (non-json) {line[:200]}", file=sys.stderr); continue
            print(f"<-- {json.dumps(obj)[:300]}", file=sys.stderr)
            if pred(obj):
                return obj

    try:
        # 1) initialize  (spike finding: adapter 0.42.0 negotiates protocolVersion 1)
        init_id = send("initialize", {"protocolVersion": 1, "capabilities": {},
                                      "clientInfo": {"name": "agenticops-spike", "version": "0"}})
        await proc.stdin.drain()
        init = await read_until(lambda o: o.get("id") == init_id and "result" in o, "initialize")
        print("=== INITIALIZE RESULT ===", file=sys.stderr)
        print(json.dumps(init.get("result", {}), indent=2), file=sys.stderr)

        # 2) session/new  (cwd = project root)
        cwd = os.getcwd()
        sid_id = send("session/new", {"cwd": cwd, "mcpServers": []})
        await proc.stdin.drain()
        # Note: agent may interleave session/request_permission — auto-allow if so.
        async def pump_until_result(rid, label):
            while True:
                raw = await asyncio.wait_for(proc.stdout.readline(), 120)
                if not raw:
                    raise RuntimeError(f"closed while waiting {label}")
                line = raw.decode().strip()
                if not line:
                    continue
                obj = json.loads(line)
                print(f"<-- {json.dumps(obj)[:300]}", file=sys.stderr)
                # auto-approve any permission request
                if obj.get("method") == "session/request_permission":
                    opts = obj["params"].get("options", [])
                    pick = next((o for o in opts if o.get("kind") == "allow_once"), opts[0] if opts else None)
                    proc.stdin.write((json.dumps({"jsonrpc": "2.0", "id": obj["id"],
                        "result": {"outcome": {"outcome": "selected", "optionId": pick.get("optionId")}}}) + "\n").encode())
                    await proc.stdin.drain(); continue
                if obj.get("id") == rid and ("result" in obj or "error" in obj):
                    return obj
        sess = await pump_until_result(sid_id, "session/new")
        session_id = sess.get("result", {}).get("sessionId")
        print(f"=== sessionId = {session_id} ===", file=sys.stderr)

        # 3) session/prompt  + stream session/update
        pid = send("session/prompt", {"sessionId": session_id,
                                      "prompt": [{"type": "text", "text": prompt}]})
        await proc.stdin.drain()
        text_acc = []
        while True:
            raw = await asyncio.wait_for(proc.stdout.readline(), 120)
            if not raw:
                break
            line = raw.decode().strip()
            if not line:
                continue
            obj = json.loads(line)
            print(f"<-- {json.dumps(obj)[:300]}", file=sys.stderr)
            if obj.get("method") == "session/update":
                u = obj["params"].get("update", obj["params"])
                if u.get("sessionUpdate") == "agent_message_chunk":
                    text_acc.append(u.get("content", {}).get("text", ""))
            if obj.get("method") == "session/request_permission":
                opts = obj["params"].get("options", [])
                pick = next((o for o in opts if o.get("kind") == "allow_once"), opts[0] if opts else None)
                proc.stdin.write((json.dumps({"jsonrpc": "2.0", "id": obj["id"],
                    "result": {"outcome": {"outcome": "selected", "optionId": pick.get("optionId")}}}) + "\n").encode())
                await proc.stdin.drain()
            if obj.get("id") == pid and ("result" in obj or "error" in obj):
                print(f"=== PROMPT DONE: {json.dumps(obj.get('result') or obj.get('error'))} ===", file=sys.stderr)
                break
        print("=== ACCUMULATED TEXT ===")
        print("".join(text_acc))
        return 0
    finally:
        try:
            proc.terminate()
        except ProcessLookupError:
            pass


if __name__ == "__main__":
    p = sys.argv[1] if len(sys.argv) > 1 else "Reply with exactly one word: hello"
    sys.exit(asyncio.run(main(p)))
