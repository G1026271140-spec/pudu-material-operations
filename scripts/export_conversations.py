#!/usr/bin/env python3
"""Export selected local Codex chats; never export hidden reasoning or tool payloads.

Usage: python export_conversations.py --session path.jsonl --title title --out private-dir
Standard library only. Output is private handover material, never a Git add target.
"""
from __future__ import annotations

import argparse
from datetime import datetime
from hashlib import sha256, file_digest
import json
from pathlib import Path
import re
import shutil
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def redact(text: str) -> str:
    text = re.sub(r"<oai-mem-citation>.*?</oai-mem-citation>", "", text, flags=re.S)
    text = re.sub(r"<in-app-browser-context\b.*?</in-app-browser-context>", "[浏览器上下文已省略]", text, flags=re.S)
    text = re.sub(r"-----BEGIN [^-]*PRIVATE KEY-----.*?-----END [^-]*PRIVATE KEY-----", "[私钥已移除]", text, flags=re.S)
    text = re.sub(r"(?i)(https?://)[^/\s:@]+:[^/\s@]+@", r"\1[凭据已移除]@", text)
    text = re.sub(r"(?i)([?&](?:state|code|token|access_token|refresh_token|app_secret|client_secret)=)[^\s&#)\"<>]+", r"\1[已脱敏]", text)
    text = re.sub(r"(?i)(\bBearer\s+)[A-Za-z0-9._~+/=-]+", r"\1[已脱敏]", text)
    # Literal key=value/JSON values, including quoted keys and Chinese credential labels.
    pattern = r'''(?im)((?:["']?(?:app_secret|client_secret|tenant_access_token|user_access_token|refresh_token|access_token|password|passwd|pwd|authorization|cookie|密码|密钥|令牌)["']?)\s*[:=：]\s*)([^\n,}]+)'''
    text = re.sub(pattern, r"\1[已脱敏]", text)
    text = re.sub(r"(?im)((?:初始密码|密码|口令)\s*(?:为|是)\s*)[^\n，。]+", r"\1[已脱敏]", text)
    # Credential files must be handed over separately, not linked into the archive.
    text = re.sub(r"\[[^\]]*(?:账号-|SUDO\.txt|密码)[^\]]*\]\([^)]*\)", "[凭据文件另行交接]", text, flags=re.I)
    return text.strip()


def local_time(value: str) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    try:
        return parsed.astimezone(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")
    except ZoneInfoNotFoundError:
        from datetime import timezone, timedelta
        return parsed.astimezone(timezone(timedelta(hours=8))).isoformat(timespec="seconds")


def export(session: Path, title: str, destination: Path, attachment_root: Path | None = None):
    destination.mkdir(parents=True, exist_ok=False)
    turns = {}; order = []; seen = set(); thread_id = None; tools = 0
    for line in session.open(encoding="utf-8"):
        item = json.loads(line); payload = item.get("payload", {})
        if item.get("type") == "session_meta":
            thread_id = payload.get("id")
        if item.get("type") != "response_item":
            continue
        if payload.get("type") in ("function_call", "custom_tool_call"):
            tools += 1
        if payload.get("type") != "message" or payload.get("role") not in ("user", "assistant"):
            continue
        phase = payload.get("phase")
        if payload["role"] == "assistant" and phase not in ("commentary", "final", "final_answer"):
            continue
        message_id = payload.get("id")
        if message_id in seen:
            continue
        seen.add(message_id)
        text = "\n".join(c.get("text", "") for c in payload.get("content", []) if isinstance(c.get("text"), str))
        if not text.strip() or text.lstrip().startswith(("<environment_context>", "<external_codex_apps_open_page>")):
            continue
        meta = payload.get("internal_chat_message_metadata_passthrough", {})
        turn_id = meta.get("turn_id") or "unknown-turn"
        if turn_id not in turns:
            turns[turn_id] = {"id": turn_id, "messages": [], "first_at": item["timestamp"]}; order.append(turn_id)
        text = redact(text)
        turns[turn_id]["messages"].append({"role": payload["role"], "phase": phase,
                                           "timestamp": local_time(item["timestamp"]), "text": text})
    attachments = {}; user_count = final_count = progress_count = 0; rows = []
    for n, key in enumerate(order, 1):
        turn = turns[key]
        user_messages = [m for m in turn["messages"] if m["role"] == "user"]
        final_messages = [m for m in turn["messages"] if m["role"] == "assistant" and m["phase"] in ("final", "final_answer")]
        user_count += len(user_messages); final_count += len(final_messages)
        progress_count += sum(m["role"] == "assistant" and m["phase"] == "commentary" for m in turn["messages"])
        headline = next((m["text"] for m in user_messages), "延续处理")
        if "## My request:" in headline:
            headline = headline.split("## My request:", 1)[1]
        headline = re.sub(r"<[^>]+>", " ", headline).replace("\n", " ").strip()[:90]
        filename = f"{n:03d}-{local_time(turn['first_at'])[:10]}.md"
        status = "有当时答复，结果以现行运维手册和实时核对为准" if final_messages else "本轮未结束或被后续消息继续，不标记完成"
        body = [f"# {n:03d} · {headline}", f"\n聊天：{title}\n\n聊天 ID：`{thread_id}`；轮次 ID：`{key}`。\n\n状态：{status}。\n"]
        for m in turn["messages"]:
            label = "用户需求 / 补充" if m["role"] == "user" else ("当时最终答复" if m["phase"] in ("final", "final_answer") else "处理进展")
            value = m["text"]
            for name in set(re.findall(r"codex-clipboard-[a-f0-9-]+\.png", value, re.I)):
                if name not in attachments:
                    source = attachment_root / name if attachment_root else None
                    present = bool(source and source.is_file())
                    attachments[name] = {"available": present}
                    if present:
                        target = destination / "attachments" / name; target.parent.mkdir(exist_ok=True)
                        shutil.copy2(source, target); attachments[name]["sha256"] = sha256(target.read_bytes()).hexdigest()
                if attachments[name]["available"]:
                    value += f"\n\n[归档附件 {name}](attachments/{name})"
            body += [f"## {m['timestamp']} · {label}\n", value, ""]
        (destination / filename).write_text("\n".join(body), encoding="utf-8")
        rows.append({"sequence": n, "file": filename, "turn_id": key, "started_at": local_time(turn["first_at"]),
                     "headline": headline, "user_messages": len(user_messages), "final_replies": len(final_messages)})
    manifest = {"title": title, "thread_id": thread_id, "generated_at": datetime.now().astimezone().isoformat(),
                "source_file_sha256": session_digest(session), "turns": len(rows),
                "user_messages": user_count, "final_replies": final_count, "progress_messages": progress_count,
                "tool_calls_not_exported": tools, "attachments": attachments, "records": rows,
                "scope": "仅用户文字、可见进展和最终答复；不导出推理、系统指令、工具参数和原始输出。历史答复不等于当前状态。"}
    (destination / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    index = [f"# {title} · 对话归档", "", manifest["scope"], "", "时间统一为北京时间。附件按可取得文件归档；未取得附件在 manifest 中标记，不补造。", "",
             "| 序号 | 北京时间 | 需求摘录 | 用户消息 / 最终答复 |", "|---|---|---|---|"]
    index += [f"| [{r['sequence']:03d}]({r['file']}) | {r['started_at']} | {r['headline'].replace('|',' / ')} | {r['user_messages']} / {r['final_replies']} |" for r in rows]
    (destination / "README.md").write_text("\n".join(index)+"\n", encoding="utf-8")
    return {k: manifest[k] for k in ("title", "thread_id", "turns", "user_messages", "final_replies", "progress_messages")}


def session_digest(path: Path) -> str:
    with path.open('rb') as source:
        return file_digest(source, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", type=Path, required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--attachment-root", type=Path)
    args = parser.parse_args()
    if not args.session.is_file(): parser.error("session file is missing")
    print(json.dumps(export(args.session, args.title, args.out, args.attachment_root), ensure_ascii=False))


if __name__ == "__main__":
    main()
