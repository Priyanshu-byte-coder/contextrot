# contextrot

Find out where **your** coding agent starts degrading — a personal context-rot
report from the transcripts Claude Code and OpenCode already write to your disk.
Runs fully local; nothing is uploaded.

```sh
npx contextrot
```

This npm package is a thin launcher around the
[Python CLI](https://github.com/Priyanshu-byte-coder/contextrot): it runs
`uvx contextrot`, which fetches the latest release from PyPI in an isolated
environment. It needs [uv](https://docs.astral.sh/uv/) (or an existing
`pip install contextrot`) and prints one-line install instructions if neither
is found.

Full documentation, methodology, and reports:
**https://github.com/Priyanshu-byte-coder/contextrot**
