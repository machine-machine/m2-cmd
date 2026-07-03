# m2-cmd

`m2-cmd` is the headless Ornith-backed command agent.

## Install (one command, no checkout needed)

```bash
curl -fsSL https://raw.githubusercontent.com/machine-machine/m2-cmd/main/install-m2.sh | bash
```

This installs a `m2` command that turns your prompt into safe shell commands.

If you already have the repo checked out:

```bash
cd /home/m2spark1/tools/m2-cmd
./install-m2.sh
# or
./tools/m2-cmd/install.sh
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