#!/usr/bin/env python3
"""PreToolUse hook for Bash: block creating git branches with unsuitable names.

Cloudflare Pages truncates preview branch aliases to 28 characters and lowercases and
hyphenates everything else, which breaks preview URLs registered for auth and CORS
unless the name is already flat, lowercase and hyphenated.
"""
import json
import re
import shlex
import sys

MAX_LEN = 28
FLAT_NAME = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
SEPARATORS = {";", "&&", "||", "|", "&", "|&", "(", ")"}
SHELLS = {"bash", "sh", "zsh"}
WRAPPERS = {"env", "command", "sudo", "time", "rtk", "exec", "nohup"}
# git global options that consume the following token
GIT_GLOBAL_WITH_VALUE = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"}
# `git branch` options that consume the following token
BRANCH_WITH_VALUE = {
    "-u", "--set-upstream-to", "--contains", "--no-contains", "--merged", "--no-merged",
    "--points-at", "--sort", "--format", "--abbrev", "--column", "-t",
}
BRANCH_NON_CREATE = {
    "-d", "-D", "--delete", "-l", "--list", "-r", "--remotes", "-a", "--all", "-v", "-vv",
    "--verbose", "--show-current", "--unset-upstream", "--edit-description",
    "--contains", "--no-contains", "--merged", "--no-merged", "--points-at",
}
BRANCH_RENAME_COPY = {"-m", "-M", "--move", "-c", "-C", "--copy"}


def value_of(args, short_flags, long_flags):
    """Return the branch name following any of the given flags, or None."""
    for i, tok in enumerate(args):
        if tok == "--":
            break
        for flag in long_flags:
            if tok == flag and i + 1 < len(args):
                return args[i + 1]
            if tok.startswith(flag + "="):
                return tok[len(flag) + 1:]
        if tok in short_flags and i + 1 < len(args):
            return args[i + 1]
        if tok.startswith("-") and not tok.startswith("--") and len(tok) > 2:
            # clustered short flags such as -bNAME or -tb NAME
            for flag in short_flags:
                letter = flag[1]
                idx = tok.find(letter, 1)
                if idx != -1:
                    rest = tok[idx + 1:]
                    if rest:
                        return rest
                    if i + 1 < len(args):
                        return args[i + 1]
    return None


def branch_create_name(args):
    flags = {t for t in args if t.startswith("-")}
    if flags & BRANCH_RENAME_COPY:
        positional = [t for t in args if not t.startswith("-")]
        return positional[-1] if positional else None
    if flags & BRANCH_NON_CREATE:
        return None
    skip = False
    for tok in args:
        if skip:
            skip = False
            continue
        if tok in BRANCH_WITH_VALUE:
            skip = True
            continue
        if tok.startswith("-"):
            continue
        return tok
    return None


def new_branch_name(git_args):
    i = 0
    while i < len(git_args) and git_args[i].startswith("-"):
        i += 2 if git_args[i] in GIT_GLOBAL_WITH_VALUE else 1
    if i >= len(git_args):
        return None
    sub, args = git_args[i], git_args[i + 1:]
    if sub == "checkout":
        return value_of(args, ["-b", "-B"], [])
    if sub == "switch":
        return value_of(args, ["-c", "-C"], ["--create", "--force-create"])
    if sub == "branch":
        return branch_create_name(args)
    if sub == "worktree" and args and args[0] == "add":
        return value_of(args[1:], ["-b", "-B"], [])
    return None


def segments(command):
    for line in command.splitlines():
        try:
            lexer = shlex.shlex(line, posix=True, punctuation_chars=True)
            lexer.whitespace_split = True
            tokens = list(lexer)
        except ValueError:
            continue
        current = []
        for tok in tokens:
            if tok in SEPARATORS or (tok and set(tok) <= set(";&|()")):
                if current:
                    yield current
                current = []
            else:
                current.append(tok)
        if current:
            yield current


def branch_names(command, depth=0):
    for seg in segments(command):
        start = 0
        while start < len(seg) and (
            seg[start] in WRAPPERS or ("=" in seg[start] and not seg[start].startswith("-"))
        ):
            start += 1
        if start < len(seg) and seg[start].rsplit("/", 1)[-1] == "git":
            name = new_branch_name(seg[start + 1:])
            if name is not None:
                yield name
        if depth < 3:
            for i, tok in enumerate(seg[:-1]):
                if tok.rsplit("/", 1)[-1] in SHELLS and any(
                    t.startswith("-") and "c" in t for t in seg[i + 1:-1]
                ):
                    yield from branch_names(seg[-1], depth + 1)


def name_problem(name):
    if len(name) > MAX_LEN:
        return (
            f"is {len(name)} characters (length rule: the limit is {MAX_LEN}). Cloudflare Pages "
            "truncates preview branch aliases to 28 characters, which breaks preview URLs. "
            "Choose a shorter flat, hyphenated branch name."
        )
    if not FLAT_NAME.match(name):
        return (
            "is not flat lowercase hyphenated (format rule: must match "
            f"{FLAT_NAME.pattern}). Cloudflare Pages lowercases and hyphenates the alias, so only "
            "such names map 1:1 to the preview URL, and slashes are against project convention. "
            "Use only a-z, 0-9 and single hyphens, e.g. fix-auth-token-expiry."
        )
    return None


def main():
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        return 0
    if payload.get("tool_name") != "Bash":
        return 0
    command = (payload.get("tool_input") or {}).get("command") or ""
    for name in branch_names(command):
        problem = name_problem(name)
        if problem:
            print(f"Blocked: branch name '{name}' {problem}", file=sys.stderr)
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
