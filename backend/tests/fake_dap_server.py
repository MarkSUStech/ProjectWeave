"""离线测试用假 lldb-dap（子进程运行，stdin/stdout 说 DAP）。

真实响应/事件序列，便于无 Docker 环境覆盖调试会话 API 的完整生命周期。
行为由环境变量 FAKE_DAP_SCRIPT 控制（JSON：断点停行、栈帧序列）。
"""

import json
import os
import sys
import threading
import time


def read_message(stream):
    headers = {}
    while True:
        line = stream.readline()
        if not line or line in (b"\r\n", b"\n"):
            break
        if b":" in line:
            key, _, value = line.partition(b":")
            headers[key.strip().lower()] = value.strip()
    length = int(headers.get(b"content-length", b"0"))
    body = stream.read(length)
    return json.loads(body.decode("utf-8"))


def write_message(stream, payload):
    body = json.dumps(payload).encode("utf-8")
    stream.write(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body)
    stream.flush()


def response(request, body=None, success=True, message=None):
    payload = {
        "seq": 0, "type": "response",
        "command": request.get("command"),
        "request_seq": request.get("seq"),
        "success": success,
    }
    if message:
        payload["message"] = message
    if body is not None:
        payload["body"] = body
    return payload


def event(name, body=None):
    return {"seq": 0, "type": "event", "event": name, "body": body or {}}


def main():
    # FAKE_DAP_SCRIPT: {"stopLine": 17, "locals": {"x": "40"}, "frames": [...]}
    script = json.loads(os.environ.get("FAKE_DAP_SCRIPT", "{}"))
    stop_line = script.get("stopLine", 17)
    entry = script.get("entry", "src/main.cpp")
    locals_map = script.get("locals", {"x": "40", "y": "42"})
    recursion_frames = script.get("recursionFrames", [])
    out = sys.stdout.buffer
    stream = sys.stdin.buffer
    current_line = stop_line
    current_frames = [[{"id": 0, "name": "main", "file": entry, "line": stop_line}]]
    bp_lines = set(script.get("breakpointLines", [stop_line]))
    state = {"in_recursion": False}

    def send_later(delay, payload):
        def _send():
            time.sleep(delay)
            write_message(out, payload)
        threading.Thread(target=_send, daemon=True).start()

    while True:
        try:
            request = read_message(stream)
        except (ValueError, OSError):
            break
        command = request.get("command")
        args = request.get("arguments") or {}

        if command == "initialize":
            write_message(out, response(request, {"capabilities": {"supportsConfigurationDoneRequest": True}}))
        elif command == "launch":
            write_message(out, response(request))
            write_message(out, event("process", {"name": "fake-app", "systemProcessId": 4242, "startMethod": "launch"}))
            write_message(out, event("initialized"))
        elif command == "setBreakpoints":
            requested = [bp.get("line") for bp in (args.get("breakpoints") or [{"line": l} for l in args.get("lines", [])])]
            bp_lines.update(requested)
            write_message(out, response(request, {
                "breakpoints": [{"line": line, "verified": line > 0, "id": 1000 + i}
                                 for i, line in enumerate(requested)]
            }))
        elif command == "configurationDone":
            write_message(out, response(request))
            send_later(0.05, event("stopped", {"reason": "breakpoint", "threadId": 1, "allThreadsStopped": True}))
        elif command == "threads":
            write_message(out, response(request, {"threads": [{"id": 1, "name": "fake-app"}]}))
        elif command == "stackTrace":
            frames = []
            for idx, frame in enumerate(current_frames[-1]):
                frames.append({
                    "id": idx,
                    "name": frame["name"],
                    "line": frame["line"],
                    "column": 1,
                    "source": {"name": frame["file"].rsplit("/", 1)[-1], "path": f"/sandbox/work/{frame['file']}"},
                })
            write_message(out, response(request, {"stackFrames": frames, "totalFrames": len(frames)}))
        elif command == "scopes":
            write_message(out, response(request, {"scopes": [
                {"name": "Locals", "variablesReference": 1000, "expensive": False},
                {"name": "Globals", "variablesReference": 2000, "expensive": True},
            ]}))
        elif command == "variables":
            ref = args.get("variablesReference")
            if ref == 1000:
                variables = [{"name": k, "value": v, "type": "int", "variablesReference": 0}
                             for k, v in locals_map.items()]
            elif ref == 2000:
                variables = [{"name": "globalVar", "value": "1", "variablesReference": 0}]
            elif ref == 3000:
                variables = [{"name": "inner", "value": "7", "variablesReference": 0}]
            else:
                variables = []
            write_message(out, response(request, {"variables": variables}))
        elif command in ("next", "stepIn", "stepOut"):
            current_line += 1
            current_frames[-1] = [{"id": 0, "name": "main", "file": entry, "line": current_line}]
            write_message(out, response(request))
            send_later(0.05, event("stopped", {"reason": "step", "threadId": 1, "allThreadsStopped": True}))
        elif command == "continue":
            write_message(out, response(request, {"allThreadsContinued": True}))
            write_message(out, event("continued", {"threadId": 1, "allThreadsContinued": True}))
            if state["in_recursion"] is False and recursion_frames:
                state["in_recursion"] = True
                current_frames.append(recursion_frames)
                send_later(0.05, event("stopped", {"reason": "breakpoint", "threadId": 1, "allThreadsStopped": True}))
            else:
                send_later(0.1, event("exited", {"exitCode": 0}))
                send_later(0.12, event("terminated"))
        elif command == "pause":
            write_message(out, response(request))
            send_later(0.05, event("stopped", {"reason": "pause", "threadId": 1, "allThreadsStopped": True}))
        elif command == "disconnect":
            write_message(out, response(request))
            write_message(out, event("terminated"))
            break
        elif command == "terminate":
            write_message(out, response(request))
            write_message(out, event("terminated"))
            break
        else:
            write_message(out, response(request, success=False, message=f"unsupported: {command}"))


if __name__ == "__main__":
    main()
