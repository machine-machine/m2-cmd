# m2-cmd

`m2-cmd` is the headless Ornith-backed command agent.

Welcome to **m2-cmd**: your lazy, slightly suspicious but mostly reliable unix sidekick.
It reads your sentence, whispers a single command to the terminal, and runs it (unless it smells like chaos).

If you treat it like a caffeinated intern with good manners, it is fast, polite, and rarely drops things in `/dev/null` unless you ask.

## Quick start (very easy)

Type:
```bash
m2 "list files in current directory"
```
It runs:
```bash
ls
```

Type:
```bash
m2 "delete logs in /tmp"
```
It prints a colorful warning and asks before executing destructive commands.

Type:
```bash
m2 --dry-run "show current directory files"
```
It prints the generated command without running it.


## Install (one command, no checkout needed)

```bash
curl -fsSL https://github.com/machine-machine/m2-cmd/raw/refs/heads/main/install-m2.sh | bash -s -- --add-path
```

This installs a `m2` command that turns your prompt into safe shell commands.

Works in macOS (zsh default) and Linux shells. The `--add-path` flag adds the install directory to your shell profile for future shells.

If you do not want the installer to edit your shell profile, run:

```bash
curl -fsSL https://github.com/machine-machine/m2-cmd/raw/refs/heads/main/install-m2.sh | bash -s --
```

If a CDN serves a stale raw GitHub file, this cache-busting variant is equivalent:

```bash
curl -fsSL 'https://raw.githubusercontent.com/machine-machine/m2-cmd/main/install-m2.sh?cachebust=1' | bash -s -- --add-path
```

If you already have the repo checked out:

```bash
cd /home/m2spark1/tools/m2-cmd
./install-m2.sh
# or
./tools/m2-cmd/install.sh

# If PATH wasn't updated, do:
./tools/m2-cmd/install.sh --add-path
```

## Update / force reinstall (one command)

Use this when you already installed `m2` and want to pull the latest installer + agent files, or if your local copy got stuck on stale raw GitHub content:

```bash
rm -rf "$HOME/.local/share/m2-cmd" && M2_CMD_REMOTE_BASE_URL="https://github.com/machine-machine/m2-cmd/raw/refs/heads/main" bash -c 'curl -fsSL "$M2_CMD_REMOTE_BASE_URL/install-m2.sh" | bash -s -- --add-path'
```

Then either open a new shell or run:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

Verify the installed copy:

```bash
m2 --help
```

## Remove

```bash
./tools/m2-cmd/uninstall.sh --yes
```

If you want to keep captured state files:

```bash
./tools/m2-cmd/uninstall.sh --yes --keep-state
```

### Notes

- Uses model `ornith-coding` by default
- Uses endpoint `http://192.168.31.99:4000/v1/chat/completions`
- Blocks destructive commands (`rm`, `mv`, `dd`, etc.) by default, prints a colorful warning to stderr, asks for `y/N` confirmation in interactive terminals, and keeps stdout pipe-friendly
- Preserves complete multi-line shell snippets, heredocs, and composed pipelines when a task needs more than one command
- Baseline host context is saved to `~/.config/m2-agent/baseline-context.json` on install
