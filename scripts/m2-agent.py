#!/usr/bin/env python3
"""m2-headless agent.

Transforms plain-language prompts into shell commands using Ornith (OpenAI-compatible)
and executes non-destructive results.

Unsafe/dangerous commands are returned with a warning comment and are not executed.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple
from urllib import error as url_error
from urllib import request


CONFIG_DIR = Path.home() / ".config" / "m2-agent"
CONFIG_FILE = CONFIG_DIR / "config.json"
CONTEXT_FILE = CONFIG_DIR / "baseline-context.json"

DEFAULT_ENDPOINT = "http://192.168.31.99:4000/v1/chat/completions"
DEFAULT_MODEL = "ornith-coding"
DEFAULT_TIMEOUT = 45


@dataclass(frozen=True)
class DangerousRule:
    token: str
    reason: str


DANGEROUS_RULES: Tuple[DangerousRule, ...] = (
    DangerousRule("rm", "DESTRUCTIVE: removes files/directories"),
    DangerousRule("rmdir", "DESTRUCTIVE: removes directories"),
    DangerousRule("unlink", "DESTRUCTIVE: removes files"),
    DangerousRule("mv", "MOVE operation can relocate/replace files"),
    DangerousRule("shred", "DESTRUCTIVE: overwrite + delete data"),
    DangerousRule("dd", "DESTRUCTIVE: raw/block-level write"),
    DangerousRule("mkfs", "DESTRUCTIVE: filesystem format"),
    DangerousRule("truncate", "DESTRUCTIVE: truncates files"),
    DangerousRule("chmod", "PERMISSION change can lock filesystems/paths"),
    DangerousRule("chown", "PERMISSION change can lock access paths"),
    DangerousRule("chgrp", "PERMISSION change can alter security/access"),
    DangerousRule("kill", "PROCESS termination"),
    DangerousRule("killall", "PROCESS termination"),
    DangerousRule("reboot", "HOST restart operation"),
    DangerousRule("shutdown", "HOST power-off/reboot"),
    DangerousRule("poweroff", "HOST power-off operation"),
    DangerousRule("halt", "HOST stop operation"),
    DangerousRule("systemctl", "SERVICE/system state change operation"),
)


def _read_os_release() -> Dict[str, str]:
    path = Path("/etc/os-release")
    if not path.exists():
        return {}
    values: Dict[str, str] = {}
    try:
        for line in path.read_text(errors="ignore").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            values[key.strip()] = val.strip().strip('"')
    except OSError:
        return {}
    return values


def collect_baseline_context() -> Dict[str, object]:
    os_release = _read_os_release()
    uname = platform.uname()

    # Disk info for primary filesystem only; keep this lightweight.
    try:
        usage = shutil.disk_usage(str(Path.home()))
        disk = {
            "path": str(Path.home()),
            "total_bytes": usage.total,
            "used_bytes": usage.used,
            "free_bytes": usage.free,
        }
    except OSError:
        disk = {}

    py = sys.version.replace("\n", " ")

    return {
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "host": {
            "hostname": platform.node(),
            "os": {
                "pretty_name": os_release.get("PRETTY_NAME", uname.system),
                "id": os_release.get("ID", ""),
                "version": os_release.get("VERSION_ID", ""),
            },
            "platform": uname.system,
            "release": uname.release,
            "machine": uname.machine,
        },
        "python": {
            "executable": sys.executable,
            "version": py,
        },
        "env": {
            "user": os.environ.get("USER", ""),
            "home": str(Path.home()),
            "shell": os.environ.get("SHELL", ""),
            "cwd": os.getcwd(),
            "path_head": os.environ.get("PATH", "").split(":")[:8],
            "lang": os.environ.get("LANG", ""),
            "locale": os.environ.get("LC_ALL", ""),
            "term": os.environ.get("TERM", ""),
        },
        "cpu": {
            "count": os.cpu_count(),
            "machine": platform.machine(),
        },
        "disk": disk,
    }


def read_config() -> Dict[str, Any]:
    if not CONFIG_FILE.exists():
        raise SystemExit(
            "m2 not installed for this user yet. Run: python3 scripts/m2-agent.py --install"
        )
    with CONFIG_FILE.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def write_json(path: Path, payload: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
    path.chmod(0o600)


def install_command(args: argparse.Namespace) -> int:
    cfg: Dict[str, object] = {
        "backend_url": args.backend_url,
        "model": args.model,
        "api_key": args.api_key,
        "timeout": args.timeout,
        "script_path": str(Path(__file__).resolve()),
    }

    write_json(CONFIG_FILE, cfg)

    context = collect_baseline_context()
    write_json(CONTEXT_FILE, context)

    bin_path = Path(args.bin)
    bin_path.parent.mkdir(parents=True, exist_ok=True)

    script_path = str(cfg.get("script_path", Path(__file__).resolve()))
    wrapper = f'''#!/usr/bin/env bash
exec /usr/bin/env python3 {shlex.quote(script_path)} "$@"
'''
    with bin_path.open("w", encoding="utf-8") as fh:
        fh.write(wrapper)
    bin_path.chmod(0o755)

    print(f"installed: {bin_path}")
    print("baseline context:", CONFIG_DIR / "baseline-context.json")
    if str(bin_path.parent) not in os.environ.get("PATH", "").split(":"):
        print(f"PATH update needed: export PATH=\"{bin_path.parent}:$PATH\"")
    return 0


def load_baseline_context() -> Dict[str, object]:
    if not CONTEXT_FILE.exists():
        return {}
    with CONTEXT_FILE.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _clean_command(raw: str) -> str:
    raw = raw.strip()
    if not raw:
        return raw

    # Remove fenced code blocks if model leaks markdown.
    fenced = re.search(r"```(?:bash|sh)?\n([\s\S]*?)\n```", raw, flags=re.IGNORECASE)
    if fenced:
        raw = fenced.group(1).strip()

    # Remove common preambles like "Command:".
    raw = re.sub(r"^(?:command|cmd)\s*[:：]\s*", "", raw, flags=re.IGNORECASE).strip()

    # Keep only first non-empty non-comment line to produce one command string.
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    for line in lines:
        if line.startswith("#"):
            continue
        if "```" in line:
            continue
        return line
    return lines[0] if lines else ""


def _lead_effective_token(segment: str) -> str:
    try:
        tokens = shlex.split(segment)
    except ValueError:
        return segment.split(maxsplit=1)[0] if segment.split() else ""

    # Drop variable assignments and common wrappers.
    while tokens and (
        "=" in tokens[0] and not tokens[0].startswith("/")
    ):
        tokens = tokens[1:]
    while tokens and tokens[0] in {"sudo", "env", "command", "nohup", "setsid", "timeout"}:
        tokens = tokens[1:]
    return tokens[0] if tokens else ""


def classify_danger(cmd: str) -> List[str]:
    # Split on command separators.
    segments = [seg.strip() for seg in re.split(r"\s*(?:&&|\|\||;|\n)\s*", cmd) if seg.strip()]
    dangers: List[str] = []

    for seg in segments:
        token = _lead_effective_token(seg).lower()
        if not token:
            continue

        for rule in DANGEROUS_RULES:
            if token == rule.token:
                dangers.append(rule.reason)

        # Explicit /dev writes / destructive redirections.
        if re.search(r">\s*/(etc|sys|proc|dev|boot|root|bin|sbin|usr|etc/|var/)", seg):
            dangers.append("DESTRUCTIVE redirection to system path")

        # Python one-liners that remove files.
        if token in {"python", "python3", "perl", "ruby"} and re.search(r"\b(os|shutil)\.(remove|rmtree|unlink)\b", seg):
            dangers.append("DESTRUCTIVE: destructive script-based file operation")

    # Deduplicate while preserving order.
    seen: set[str] = set()
    out: List[str] = []
    for item in dangers:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _host_platform(context: Dict[str, object]) -> str:
    host = context.get("host") if isinstance(context, dict) else {}
    if not isinstance(host, dict):
        return platform.system()
    value = host.get("platform")
    return str(value) if value else platform.system()


def normalize_command_for_platform(cmd: str, context: Dict[str, object]) -> str:
    """Patch common GNU/BSD command mismatches before execution.

    The model sometimes emits GNU-only snippets for macOS. Keep the normalizer
    deliberately narrow: only rewrite known-incompatible patterns into equivalent
    BSD/POSIX commands, leaving everything else untouched.
    """
    host_platform = _host_platform(context).lower()
    if host_platform != "darwin":
        return cmd

    # GNU find: find <path> -type f -printf '%s %p\n'
    # BSD/macOS replacement: find <path> -type f -exec stat -f '%z %N' {} +
    def repl_find_printf(match: re.Match[str]) -> str:
        path_expr = match.group("path").strip()
        return f"find {path_expr} -type f -exec stat -f '%z %N' {{}} +"

    cmd = re.sub(
        r"find\s+(?P<path>(?:'[^']+'|\"[^\"]+\"|\\\S|[^|;&])+?)\s+-type\s+f\s+-printf\s+(?:'\%s\s+\%p\\n'|\"\%s\s+\%p\\n\")",
        repl_find_printf,
        cmd,
    )

    # GNU du --max-depth=N -> BSD du -d N
    cmd = re.sub(r"\bdu\s+--max-depth=(\d+)\b", r"du -d \1", cmd)
    return cmd


def local_fallback_command(prompt: str, context: Dict[str, object]) -> str:
    """Deterministic offline fallback for common tasks.

    This keeps m2 useful when the model endpoint returns empty content or emits an
    invalid command for a high-frequency request. Keep this intentionally small
    and conservative.
    """
    normalized = " ".join(prompt.lower().split())
    host_platform = _host_platform(context).lower()

    if re.search(r"\b(biggest|largest)\b", normalized) and "file" in normalized:
        if host_platform == "darwin":
            return "find \"$HOME\" -type f -exec stat -f '%z %N' {} + 2>/dev/null | sort -rn | head -20 | awk '{size=$1; $1=\"\"; sub(/^ /,\"\"); printf \"%.2f GiB %s\\n\", size/1073741824, $0}'"
        return "find \"$HOME\" -type f -printf '%s %p\\n' 2>/dev/null | sort -rn | head -20 | awk '{size=$1; $1=\"\"; sub(/^ /,\"\"); printf \"%.2f GiB %s\\n\", size/1073741824, $0}'"

    return ""


def call_ornith(prompt: str, cfg: Dict[str, Any], context: Dict[str, object]) -> str:
    model = str(cfg["model"])
    backend_url = str(cfg["backend_url"])
    api_key = str(cfg["api_key"])
    timeout = int(cfg.get("timeout", DEFAULT_TIMEOUT))
    host_platform = _host_platform(context)

    system_prompt = (
        "You are a deterministic terminal command planner named m2.\n"
        "Return exactly one shell command as plain text.\n"
        "No markdown, no quotes, no explanations.\n"
        "Prefer safe commands and minimal scope.\n"
        "Do not include backticks.\n"
        f"Target host platform: {host_platform}.\n"
        "Use commands compatible with the target host, not your own environment.\n"
        "For macOS/Darwin, avoid GNU-only flags such as find -printf, du --max-depth, GNU stat -c, and GNU date -d; use BSD/POSIX alternatives.\n"
        "For Linux, GNU coreutils/findutils syntax is allowed.\n"
    )

    user_payload = {
        "task": prompt,
        "host_context": context,
    }

    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(user_payload)},
        ],
        "temperature": 0.0,
        "max_tokens": 256,
    }

    req = request.Request(
        backend_url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except url_error.HTTPError as exc:
        raise SystemExit(f"ornith HTTP error: {exc.code} {exc.reason}")
    except url_error.URLError as exc:  # includes connection failures/timeouts
        raise SystemExit(f"ornith connection error: {exc}")
    except Exception as exc:  # pragma: no cover
        raise SystemExit(f"orchard call failed: {exc}")

    try:
        choice0 = payload["choices"][0]
        raw = choice0["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise SystemExit("ornith response missing choices/message/content")

    cmd = _clean_command(str(raw))
    if not cmd:
        fallback = local_fallback_command(prompt, context)
        if fallback:
            return fallback
        raise SystemExit("ornith returned empty command")
    return cmd


def execute_command(cmd: str, allow_dangerous: bool, dry_run: bool) -> int:
    risks = classify_danger(cmd)
    if risks and not allow_dangerous:
        warning = "; ".join(risks)
        print(f"{cmd}  # WARNING: {warning}")
        return 3

    print(cmd)
    if dry_run:
        return 0

    proc = subprocess.run(cmd, shell=True, executable="/bin/bash", text=True, capture_output=True)
    if proc.stdout:
        print(proc.stdout.rstrip())
    if proc.stderr:
        print(proc.stderr.rstrip(), file=sys.stderr)
    return proc.returncode


def parse_args(argv: List[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Headless m2 agent (Ornith-backed)")
    p.add_argument("prompt", nargs="*", help="natural-language task")
    p.add_argument(
        "--install",
        action="store_true",
        help="capture baseline env and install ~/.local/bin/m2 wrapper",
    )
    p.add_argument(
        "--show-context",
        action="store_true",
        help="print captured baseline context",
    )
    p.add_argument(
        "--show-config",
        action="store_true",
        help="print active config",
    )
    p.add_argument(
        "--backend-url",
        default=os.environ.get("M2_ORNITH_BACKEND", DEFAULT_ENDPOINT),
    )
    p.add_argument("--model", default=os.environ.get("M2_ORNITH_MODEL", DEFAULT_MODEL))
    p.add_argument(
        "--api-key",
        default=os.environ.get("M2_ORNITH_API_KEY", "sk-local"),
    )
    p.add_argument(
        "--timeout",
        type=int,
        default=int(os.environ.get("M2_ORNITH_TIMEOUT", str(DEFAULT_TIMEOUT))),
    )
    p.add_argument(
        "--bin",
        default=str(Path.home() / ".local" / "bin" / "m2"),
        help="install target for m2 command",
    )
    p.add_argument(
        "--allow-dangerous",
        action="store_true",
        help="execute commands even when classified dangerous",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="print command only, do not execute",
    )
    return p.parse_args(argv)


def main(argv: List[str]) -> int:
    args = parse_args(argv)

    if args.install:
        return install_command(args)

    cfg = read_config()

    if args.show_config:
        visible_cfg = dict(cfg)
        if isinstance(visible_cfg.get("api_key"), str):
            visible_cfg["api_key"] = "***"
        print(json.dumps(visible_cfg, indent=2))
        return 0

    if args.show_context:
        ctx = load_baseline_context()
        print(json.dumps(ctx, indent=2))
        return 0

    if not args.prompt:
        raise SystemExit("No prompt provided. Example: m2 \"list files\"")

    prompt = " ".join(args.prompt)
    baseline = load_baseline_context()
    if not baseline:
        # Fallback to a fresh one-off snapshot if install was incomplete.
        baseline = collect_baseline_context()

    cmd = call_ornith(prompt, cfg, baseline)
    if not cmd:
        fallback = local_fallback_command(prompt, baseline)
        if fallback:
            cmd = fallback
    cmd = normalize_command_for_platform(cmd, baseline)
    return execute_command(cmd, allow_dangerous=args.allow_dangerous, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
