# Copyright 2024 Caleb Connolly
# SPDX-License-Identifier: GPL-3.0-or-later

"""Posix SH lexer"""

import enum
import re
from typing import List, Optional

class Tok():
    def __init__(self, name: str, match: str, prev: List["Tok"] = [], follows: Optional["Tok"] = None, skip: bool = False):
        self.name = name
        self.match = match
        self.prev = prev
        self.follows = follows
        self.skip = skip
        
    def matches(self, contents: str, pos: int, prev: List["Tok"]):
        if self.prev:
            if not len(prev):
                return pos, None
            if prev[-1] not in self.prev:
                return pos, None
        if self.follows:
            if not len(prev):
                return pos, None
            if self.follows not in prev:
                return pos, None

        end = contents.index("\n", pos) if "\n" in contents[pos:] else len(contents)
        match = re.match(self.match, contents[pos:end])
        if match:
            group = match.group()
            return pos + match.end(), group
        return pos, None

    def __str__(self):
        return self.name


# Tokens to prioritize in matching should be at the bottom
class Tokens(enum.Enum):
    """Token types"""
    ENDQUOTE = Tok("<endquote>", r"""(?<!\)["']""", skip=True)
    QUOTE = Tok("<quote>", r"""["']""")
    COMMENT = Tok("<comment>", r"#.*")
    EQUALS = Tok("<equals>", r"=")
    IDENTIFIER = Tok("<ident>", r"[a-zA-Z_][\w_-]+")
    FUNC = Tok("<func>", r"\(\)\s?\{", prev=[IDENTIFIER])
    SEP = Tok("<sep>", r"[ \t]+")
    PIPE = Tok("<pipe>", r"\|")
    AND = Tok("<and>", r"&&")
    OR = Tok("<or>", r"\|\|")
    ENDSTMT = Tok("<semi>", "[;\n]")
    AMP = Tok("<amp>", r"&")
    REDIROUT = Tok("<out>", r">")
    REDIROUTAPPEND = Tok("<out+>", r">>")
    REDIRIN = Tok("<in>", r"<")
    REDIRINHERE = Tok("<in+>", r"<<")
    VALUE = Tok("<value>", r"[\w\._]+", prev=[EQUALS])
    # Stuff that can be passed as arguments to a function or command
    DATA = Tok("<data>", r"[\w\._]+", follows=IDENTIFIER)


def parse_string(contents: str, pos: int, quote: str):
    string = ""
    clen = len(contents)
    while pos < clen and contents[pos] != quote:
        if contents[pos] == "\\":
            pos += 1
        string += contents[pos]
        pos += 1

    if pos == clen:
        raise ValueError(f"Unterminated string: {string}")

    return pos + 1, string

    # while "\n" in contents[pos:]:
    #     print(f"{contents[pos:pos+10]}...")
    #     newpos, group = Tokens.QUOTE.value.matches(contents, pos, [])
    #     if not group or contents[newpos-1] == "\\":
    #         idx = contents.index("\n", pos)
    #         string += contents[pos:idx]
    #         pos += idx
    #     else:
    #         return newpos, string + contents[pos:newpos-1]

    # print(f"Unterminated string: {string}")
    # return pos, None

def tokenize(contents: str):
    """Tokenize a line of shell code"""
    pos = 0
    linepos = 0 # Characters until start of current line
    lines = 1
    linetoks: List[Tok] = []
    in_quote = False
    line = contents[pos:contents.index("\n", pos) if "\n" in contents[pos:] else len(contents)]
    string = ""
    while pos < len(contents):
        if contents[pos] == "\n" and contents[pos-1] != "\\": # Newline
            pos += 1
            linepos = pos + 1
            line = contents[pos:contents.index("\n", pos) if "\n" in contents[pos:] else len(contents)]
            lines += 1
            linetoks = []
            yield Tokens.ENDSTMT, "\n"
            continue
        for _tok in reversed(Tokens):
            tok = _tok.value
            if tok.skip:
                continue

            pos, group = tok.matches(contents, pos, linetoks)
            if group:
                linetoks.append(tok)
                if _tok == Tokens.QUOTE:
                    if contents[pos-1] == "\\":
                        continue
                    newpos, string = parse_string(contents, pos, group)
                    yield _tok, group
                    yield Tokens.VALUE, string
                    yield Tokens.QUOTE, group
                    linetoks = []
                    lines += contents[pos:newpos].count("\n")
                    pos = newpos
                    line = contents[pos:contents.index("\n") if "\n" in contents else len(contents)]
                elif _tok == Tokens.ENDSTMT and not in_quote:
                    linetoks = []
                    line = contents[pos:contents.index("\n") if "\n" in contents else len(contents)]
                    linepos = pos + 1
                elif _tok == Tokens.QUOTE:
                    in_quote = False
                yield tok, group
                break
        else:
            print(f"\nInvalid character at position {lines}:{pos-linepos}")
            print(f"> {line.strip()}")
            print(f"  {' ' * (pos - linepos)}^")
            print(f"Last: {linetoks[-1] if linetoks else None}")
            raise ValueError(f"Invalid character at position {pos} in line: {line}")


def test():
    """Test the lexer"""
    for line in [
        "echo hello world\n",
    ]:
        for tok, val in tokenize(line):
            print(f"{tok}:{val}", end=" ")


def run(path: str):
    """Run the lexer on a file"""
    with open(path) as file:
        for tok, val in tokenize(file.read()):
            print(f"{tok}:{val}", end=" ")
