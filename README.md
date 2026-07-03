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
It prints:
```bash
rm /tmp/*.log  # WARNING: DESTRUCTIVE: removes files/directories
```
and does not execute unless you use `--allow-dangerous`.

Type:
```bash
m2 --dry-run "show current directory files"
```
It prints the generated command without running it.


## Install (one command, no checkout needed)

```bash
curl -fsSL https://raw.githubusercontent.com/machine-machine/m2-cmd/main/install-m2.sh | bash
```

This installs a `m2` command that turns your prompt into safe shell commands.

If your `m2` binary is not on PATH after install (step 2), rerun with:

```bash
curl -fsSL https://raw.githubusercontent.com/machine-machine/m2-cmd/main/install-m2.sh | bash -s -- --add-path
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
- Blocks destructive commands (`rm`, `mv`, `dd`, etc.) by default and prints warning comments
- Baseline host context is saved to `~/.config/m2-agent/baseline-context.json` on install