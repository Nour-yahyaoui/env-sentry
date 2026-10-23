"""
Shell completion generation.

Generating from the live argparse parser means completions never drift from
the real CLI: add a flag and bash/zsh/fish pick it up automatically.
"""

from __future__ import annotations

import argparse
from typing import Dict, List

SHELLS = ("bash", "zsh", "fish")

INSTALL_HINTS = {
    "bash": 'eval "$(env-sentry completions bash)"   # or add to ~/.bashrc',
    "zsh": 'eval "$(env-sentry completions zsh)"     # or add to ~/.zshrc',
    "fish": "env-sentry completions fish | source    # or save to ~/.config/fish/completions",
}


def _subcommands(parser: argparse.ArgumentParser) -> Dict[str, argparse.ArgumentParser]:
    for action in parser._actions:  # noqa: SLF001 - argparse exposes no public API
        if isinstance(action, argparse._SubParsersAction):  # noqa: SLF001
            return dict(action.choices)
    return {}


def _options(parser: argparse.ArgumentParser) -> List[str]:
    options = []
    for action in parser._actions:
        options.extend(action.option_strings)
    return sorted(set(options))


def _has_positionals(parser: argparse.ArgumentParser) -> bool:
    return any(
        not action.option_strings and action.dest not in ("help",)
        and action.nargs != 0
        for action in parser._actions
    )


def bash(parser: argparse.ArgumentParser, prog: str = "env-sentry") -> str:
    subs = _subcommands(parser)
    lines = [
        f"# bash completion for {prog}",
        f"_{prog.replace('-', '_')}_complete() {{",
        "    local cur prev cmd",
        '    COMPREPLY=()',
        '    cur="${COMP_WORDS[COMP_CWORD]}"',
        '    prev="${COMP_WORDS[COMP_CWORD-1]}"',
        '    cmd="${COMP_WORDS[1]}"',
        "",
        "    if [[ $COMP_CWORD -eq 1 ]]; then",
        f'        COMPREPLY=( $(compgen -W "{ " ".join(sorted(subs)) } --version --help --color --quiet" -- "$cur") )',
        "        return 0",
        "    fi",
        "",
        '    case "$cmd" in',
    ]
    for name, sub in sorted(subs.items()):
        options = " ".join(_options(sub))
        extra = '    COMPREPLY=( $(compgen -f -- "$cur") )' if _has_positionals(sub) else ""
        lines.append(f"        {name})")
        lines.append(f'            COMPREPLY=( $(compgen -W "{options}" -- "$cur") )')
        if extra:
            lines.append(f'            [[ ${{#COMPREPLY[@]}} -eq 0 ]] && {extra.strip()}')
        lines.append("            ;;")
    lines += ["    esac", "    return 0", "}", f"complete -F _{prog.replace('-', '_')}_complete {prog}"]
    return "\n".join(lines) + "\n"


def zsh(parser: argparse.ArgumentParser, prog: str = "env-sentry") -> str:
    subs = _subcommands(parser)
    lines = [
        f"#compdef {prog}",
        f"# zsh completion for {prog}",
        f"_{prog.replace('-', '_')}() {{",
        "    local -a commands",
        "    commands=(",
    ]
    for name, sub in sorted(subs.items()):
        description = (sub.description or name).splitlines()[0].replace("'", "")
        lines.append(f"        '{name}:{description[:70]}'")
    lines += [
        "    )",
        "",
        "    _arguments -C \\",
        "        '--version[show version]' \\",
        "        '--color=[colour mode]:mode:(auto always never)' \\",
        "        '(-q --quiet)'{-q,--quiet}'[only warnings and errors]' \\",
        "        '1:command:->command' \\",
        "        '*::arg:->args'",
        "",
        "    case $state in",
        "        command) _describe 'command' commands ;;",
        "        args)",
        "            case $words[2] in",
    ]
    for name, sub in sorted(subs.items()):
        opts = " ".join(f"'{option}[{option.lstrip('-')}]'" for option in _options(sub)
                        if option not in ("-h", "--help"))
        lines.append(f"                {name}) _arguments {opts} '*:file:_files' ;;")
    lines += [
        "            esac",
        "            ;;",
        "    esac",
        "}",
        f"_{prog.replace('-', '_')} \"$@\"",
    ]
    return "\n".join(lines) + "\n"


def fish(parser: argparse.ArgumentParser, prog: str = "env-sentry") -> str:
    subs = _subcommands(parser)
    lines = [f"# fish completion for {prog}"]
    for name, sub in sorted(subs.items()):
        description = (sub.description or name).splitlines()[0].replace("'", "")
        lines.append(
            f"complete -c {prog} -n '__fish_use_subcommand' -a {name} -d '{description[:80]}'"
        )
        for option in _options(sub):
            if option in ("-h", "--help"):
                continue
            bare = option.lstrip("-")
            if option.startswith("--"):
                lines.append(f"complete -c {prog} -n '__fish_seen_subcommand_from {name}' -l {bare}")
            else:
                lines.append(f"complete -c {prog} -n '__fish_seen_subcommand_from {name}' -s {bare}")
    lines.append(f"complete -c {prog} -l version -d 'show version'")
    lines.append(f"complete -c {prog} -l color -x -a 'auto always never' -d 'colour mode'")
    return "\n".join(lines) + "\n"


RENDERERS = {"bash": bash, "zsh": zsh, "fish": fish}


def render(shell: str, parser: argparse.ArgumentParser, prog: str = "env-sentry") -> str:
    if shell not in RENDERERS:
        raise ValueError(f"unsupported shell '{shell}' (choose from {', '.join(SHELLS)})")
    return RENDERERS[shell](parser, prog)
