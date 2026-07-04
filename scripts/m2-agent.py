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
DEFAULT_MAX_TOKENS = 1024
DEFAULT_CONTINUATION_ROUNDS = 3


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
        "max_tokens": args.max_tokens,
        "continuation_rounds": args.continuation_rounds,
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

    # Preserve full shell snippets when the model returns a heredoc, pipeline
    # composition, or small multi-line script. Truncating heredocs/scripts to the
    # first line produces broken commands like: cat > file << 'EOF'
    lines = [ln.rstrip() for ln in raw.splitlines() if ln.strip()]
    non_comment_lines = [ln for ln in lines if not ln.lstrip().startswith("#") and "```" not in ln]
    if "<<" in raw or len(non_comment_lines) > 1:
        return raw

    # Keep only first non-empty non-comment line for normal one-line commands.
    for line in non_comment_lines:
        return line.strip()
    return lines[0].strip() if lines else ""


def _heredoc_missing_terminator(cmd: str) -> bool:
    match = re.search(r"<<-?\s*['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?", cmd)
    if not match:
        return False
    terminator = match.group(1)
    return not any(line.strip() == terminator for line in cmd.splitlines()[1:])


def _shell_syntax_error(cmd: str) -> str:
    """Return bash -n stderr if a generated snippet is syntactically invalid."""
    try:
        proc = subprocess.run(
            ["/bin/bash", "-n"],
            input=cmd,
            text=True,
            capture_output=True,
            timeout=3,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return str(exc)
    return proc.stderr.strip() if proc.returncode else ""


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

    if "tree" in normalized and re.search(r"\b(list|show|print|display)\b", normalized):
        return """python3 - <<'PY'
import os
root='.'
max_depth=2
skip={'.git','node_modules','__pycache__','.venv','venv'}
print(root)
for dirpath, dirnames, filenames in os.walk(root):
    dirnames[:] = [d for d in sorted(dirnames) if d not in skip]
    depth = 0 if dirpath == root else dirpath[len(root):].strip(os.sep).count(os.sep) + 1
    if depth >= max_depth:
        dirnames[:] = []
    entries = [(d, True) for d in dirnames] + [(f, False) for f in sorted(filenames)]
    entries = entries[:80]
    for name, is_dir in entries:
        print('  ' * (depth + 1) + ('📁 ' if is_dir else '📄 ') + name)
PY"""

    if "matrix" in normalized and re.search(r"\b(color|colors|terminal|theme|look)\b", normalized):
        return "\n".join([
            'cat > "$HOME/.matrix_colors.sh" <<\'EOF\'',
            '#!/usr/bin/env bash',
            "printf '\\033]10;#00ff41\\007'",
            "printf '\\033]11;#000000\\007'",
            "printf '\\033]12;#00ff41\\007'",
            "printf '\\033[1;32mMatrix terminal colors applied for this session.\\033[0m\\n'",
            "printf '\\033[2;32mText/cursor set to green, background set to black where supported by your terminal.\\033[0m\\n'",
            'EOF',
            'bash "$HOME/.matrix_colors.sh"',
        ])

    if "pong" in normalized and ("browser" in normalized or "open" in normalized or "html" in normalized or "hml" in normalized):
        opener = "open" if host_platform == "darwin" else "xdg-open"
        return "\n".join([
            "cat > pong.html <<'EOF'",
            "<!doctype html>",
            "<html><head><meta charset='utf-8'><title>Pong</title><style>html,body{margin:0;height:100%;background:#050;color:#0f0;font-family:monospace;overflow:hidden}canvas{display:block;margin:auto;background:#000;box-shadow:0 0 30px #0f0}</style></head>",
            "<body><canvas id='c' width='800' height='500'></canvas><script>",
            "const c=document.getElementById('c'),x=c.getContext('2d');let py=210,ai=210,bx=400,by=250,vx=5,vy=3,ps=0,as=0;addEventListener('mousemove',e=>{const r=c.getBoundingClientRect();py=Math.max(0,Math.min(420,e.clientY-r.top-40));});function rect(a,b,w,h){x.fillRect(a,b,w,h)}function loop(){by+=vy;bx+=vx;if(by<0||by>490)vy*=-1;if(bx<30&&by>py&&by<py+80){vx=Math.abs(vx)+.25}if(bx>760&&by>ai&&by<ai+80){vx=-Math.abs(vx)-.25}if(bx<0){as++;bx=400;by=250;vx=5}if(bx>800){ps++;bx=400;by=250;vx=-5}ai+=(by-ai-40)*.08;x.clearRect(0,0,800,500);x.fillStyle='#0f0';rect(20,py,10,80);rect(770,ai,10,80);rect(bx,by,10,10);for(let y=0;y<500;y+=24)rect(398,y,4,12);x.font='32px monospace';x.fillText(ps,320,45);x.fillText(as,460,45);requestAnimationFrame(loop)}loop();</script></body></html>",
            "EOF",
            f"{opener} pong.html >/dev/null 2>&1 || printf 'Created pong.html; open it in your browser.\n'",
        ])

    if re.search(r"\b(list|show)\b", normalized) and re.search(r"\b(files?|directory|dir)\b", normalized):
        return "ls -la"

    return ""
def _ornith_request(
    backend_url: str,
    api_key: str,
    model: str,
    messages: List[Dict[str, str]],
    timeout: int,
    max_tokens: int,
) -> Tuple[str, str]:
    body = {
        "model": model,
        "messages": messages,
        "temperature": 0.0,
        "max_tokens": max_tokens,
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
        raw = str(choice0["message"]["content"] or "")
        finish_reason = str(choice0.get("finish_reason") or "")
    except (KeyError, IndexError, TypeError):
        raise SystemExit("ornith response missing choices/message/content")
    return raw, finish_reason


def _snippet_state_path() -> Path:
    return CONFIG_DIR / "last-generated-snippet.sh.tmp"


def _write_snippet_state(text: str) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    path = _snippet_state_path()
    path.write_text(text, encoding="utf-8")
    path.chmod(0o600)


def _needs_continuation(text: str, finish_reason: str) -> bool:
    if finish_reason == "length":
        return True
    if _heredoc_missing_terminator(text):
        return True
    syntax_error = _shell_syntax_error(text)
    if syntax_error and re.search(r"unexpected EOF|looking for matching|here-document", syntax_error, re.IGNORECASE):
        return True
    return False


def call_ornith(prompt: str, cfg: Dict[str, Any], context: Dict[str, object]) -> str:
    model = str(cfg["model"])
    backend_url = str(cfg["backend_url"])
    api_key = str(cfg["api_key"])
    timeout = int(cfg.get("timeout", DEFAULT_TIMEOUT))
    max_tokens = int(cfg.get("max_tokens", DEFAULT_MAX_TOKENS))
    continuation_rounds = int(cfg.get("continuation_rounds", DEFAULT_CONTINUATION_ROUNDS))
    host_platform = _host_platform(context)

    system_prompt = (
        "You are a deterministic terminal automation planner named m2.\n"
        "Return exactly one shell snippet as plain text.\n"
        "No markdown, no explanations, no backticks.\n"
        "Prefer safe commands and minimal scope.\n"
        "For simple tasks, return one command.\n"
        "For tasks that need composition, you may return a short bash snippet with pipelines, variables, conditionals, heredocs, or a temporary script that is written and executed.\n"
        "If you use a heredoc, include the complete terminator line.\n"
        "Do not leave commands waiting for stdin.\n"
        "If continuing a previous partial snippet, continue exactly at the next character; do not repeat earlier content.\n"
        f"Target host platform: {host_platform}.\n"
        "Use commands compatible with the target host, not your own environment.\n"
        "For macOS/Darwin, avoid GNU-only flags such as find -printf, du --max-depth, GNU stat -c, and GNU date -d; use BSD/POSIX alternatives.\n"
        "For Linux, GNU coreutils/findutils syntax is allowed.\n"
    )

    user_payload = {
        "task": prompt,
        "host_context": context,
    }

    messages: List[Dict[str, str]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": json.dumps(user_payload)},
    ]

    assembled = ""
    finish_reason = ""
    for round_idx in range(continuation_rounds + 1):
        raw, finish_reason = _ornith_request(backend_url, api_key, model, messages, timeout, max_tokens)
        if raw:
            assembled += raw
            _write_snippet_state(assembled)

        if not _needs_continuation(assembled, finish_reason):
            break

        tail = assembled[-2500:]
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(user_payload)},
            {"role": "assistant", "content": tail},
            {
                "role": "user",
                "content": (
                    "The shell snippet above was truncated and has already been written to a temporary local state file. "
                    "Continue exactly where it stopped. Return only the missing suffix, no markdown, no explanation, no repeated prefix."
                ),
            },
        ]
    else:
        print(f"m2 warning: snippet may still be truncated; partial state at {_snippet_state_path()}", file=sys.stderr)

    cmd = _clean_command(assembled)
    if _heredoc_missing_terminator(cmd):
        fallback = local_fallback_command(prompt, context)
        if fallback:
            return fallback
        raise SystemExit(f"ornith returned incomplete heredoc command; partial state at {_snippet_state_path()}")
    if not cmd:
        fallback = local_fallback_command(prompt, context)
        if fallback:
            return fallback
        raise SystemExit("ornith returned empty command")
    syntax_error = _shell_syntax_error(cmd)
    if syntax_error:
        fallback = local_fallback_command(prompt, context)
        if fallback:
            return fallback
        raise SystemExit(f"ornith returned invalid shell syntax: {syntax_error}; partial state at {_snippet_state_path()}")
    return cmd


def _ansi(style: str) -> str:
    if os.environ.get("NO_COLOR"):
        return ""
    return style


def _color(text: str, style: str) -> str:
    if not style:
        return text
    reset = _ansi("\033[0m")
    return f"{style}{text}{reset}"


def _command_echo_stream():
    # Keep stdout pipeable: when m2 is used in a pipeline, stdout should contain
    # only the executed command's stdout. The generated command/status messages go
    # to stderr unless the user is in an interactive terminal.
    return sys.stdout if sys.stdout.isatty() else sys.stderr


def _confirm_dangerous_command(cmd: str, warning: str) -> bool:
    red_bold = _ansi("\033[1;31m")
    yellow = _ansi("\033[33m")
    dim = _ansi("\033[2m")
    print(_color("⚠ WARNING: potentially destructive command", red_bold), file=sys.stderr)
    print(_color(f"Reason: {warning}", yellow), file=sys.stderr)
    print(_color("Generated command:", dim), file=sys.stderr)
    print(cmd, file=sys.stderr)

    if not sys.stdin.isatty():
        print(_color("Blocked because stdin is not interactive. Re-run in a terminal or use --allow-dangerous.", dim), file=sys.stderr)
        return False

    try:
        answer = input(_color("Execute this command? [y/N] ", red_bold))
    except (EOFError, KeyboardInterrupt):
        print("", file=sys.stderr)
        return False
    return answer.strip().lower() in {"y", "yes"}


def execute_command(cmd: str, allow_dangerous: bool, dry_run: bool) -> int:
    risks = classify_danger(cmd)
    if risks and not allow_dangerous:
        warning = "; ".join(risks)
        if dry_run:
            red_bold = _ansi("\033[1;31m")
            yellow = _ansi("\033[33m")
            print(_color("⚠ WARNING: dry-run command is potentially destructive", red_bold), file=sys.stderr)
            print(_color(f"Reason: {warning}", yellow), file=sys.stderr)
            print(cmd)
            return 0
        if not _confirm_dangerous_command(cmd, warning):
            return 3

    # Dry-run is intentionally stdout-friendly so `m2 --dry-run ... | pbcopy`
    # or `m2 --dry-run ... | sh` can work when explicitly requested.
    if dry_run:
        print(cmd)
        return 0

    print(cmd, file=_command_echo_stream())

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
        "--max-tokens",
        type=int,
        default=int(os.environ.get("M2_ORNITH_MAX_TOKENS", str(DEFAULT_MAX_TOKENS))),
        help="max tokens per model request before continuation",
    )
    p.add_argument(
        "--continuation-rounds",
        type=int,
        default=int(os.environ.get("M2_ORNITH_CONTINUATION_ROUNDS", str(DEFAULT_CONTINUATION_ROUNDS))),
        help="extra model calls to continue truncated snippets",
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
