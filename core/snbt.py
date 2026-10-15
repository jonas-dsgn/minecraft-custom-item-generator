"""Small SNBT reader for the `custom_data` component.

It checks that what the user typed is a well-formed compound (so a typo cannot produce a
command Minecraft rejects) and converts it to JSON for recipe results. The command itself
always gets the user's text unchanged.

Not covered on purpose: the exotic number forms (hex, binary, underscores) and unquoted
strings containing characters outside [A-Za-z0-9_.+-].
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

_WORD = re.compile(r"[A-Za-z0-9_.+-]+")
_NUMBER = re.compile(r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?([bBsSlLfFdD]?)\Z")
_MAX_DEPTH = 32


class SnbtError(ValueError):
    def __init__(self, message: str, position: int) -> None:
        super().__init__(f"{message} (at character {position + 1})")
        self.position = position


@dataclass
class _Result:
    value: Any
    lossy: bool = False      # JSON cannot express the NBT type that was written


class _Reader:
    def __init__(self, text: str) -> None:
        self.t, self.i, self.lossy = text, 0, False

    def ws(self) -> None:
        while self.i < len(self.t) and self.t[self.i] in " \t":
            self.i += 1

    def peek(self) -> str:
        self.ws()
        return self.t[self.i] if self.i < len(self.t) else ""

    def expect(self, ch: str) -> None:
        if self.peek() != ch:
            raise SnbtError(f"expected '{ch}'", self.i)
        self.i += 1

    def value(self, depth: int = 0) -> Any:
        if depth > _MAX_DEPTH:
            raise SnbtError("nested too deeply", self.i)
        c = self.peek()
        if c == "{":
            return self.compound(depth)
        if c == "[":
            return self.list_(depth)
        if c in "\"'":
            return self.string()
        if not c:
            raise SnbtError("value expected", self.i)
        start = self.i
        m = _WORD.match(self.t, self.i)
        if not m:
            raise SnbtError(f"unexpected '{c}'", self.i)
        self.i = m.end()
        word = m.group()
        if word == "true":
            return True
        if word == "false":
            return False
        n = _NUMBER.match(word)
        if n:
            suffix = n.group(1).lower()
            body = word[:-1] if suffix else word
            if suffix in ("b", "s", "l", "f"):
                self.lossy = True                      # JSON numbers become int/double
            if suffix in ("f", "d") or any(ch in body for ch in ".eE"):
                return float(body)
            return int(body)
        if word[0].isdigit() or word[0] in "+-.":
            raise SnbtError(f"invalid number '{word}'", start)
        return word                                    # unquoted string

    def string(self) -> str:
        quote = self.t[self.i]
        self.i += 1
        out: list[str] = []
        while self.i < len(self.t):
            c = self.t[self.i]
            if c == "\\":
                if self.i + 1 >= len(self.t):
                    break
                out.append(self.t[self.i + 1])
                self.i += 2
            elif c == quote:
                self.i += 1
                return "".join(out)
            else:
                out.append(c)
                self.i += 1
        raise SnbtError("string is not closed", self.i)

    def key(self) -> str:
        if self.peek() in ("\"", "'"):
            return self.string()
        m = _WORD.match(self.t, self.i)
        if not m:
            raise SnbtError("key expected", self.i)
        self.i = m.end()
        return m.group()

    def compound(self, depth: int) -> dict[str, Any]:
        self.expect("{")
        out: dict[str, Any] = {}
        while self.peek() != "}":
            if not self.peek():
                raise SnbtError("compound is not closed, '}' missing", self.i)
            k = self.key()
            self.expect(":")
            out[k] = self.value(depth + 1)
            if self.peek() == ",":
                self.i += 1
            elif self.peek() != "}":
                raise SnbtError("',' or '}' expected", self.i)
        self.i += 1
        return out

    def list_(self, depth: int) -> list[Any]:
        self.expect("[")
        # typed arrays: [B; 1b, 2b], [I; 1, 2], [L; 1l]
        m = re.compile(r"\s*([BIL])\s*;").match(self.t, self.i)
        if m:
            self.i = m.end()
            self.lossy = True
        out: list[Any] = []
        while self.peek() != "]":
            if not self.peek():
                raise SnbtError("list is not closed, ']' missing", self.i)
            out.append(self.value(depth + 1))
            if self.peek() == ",":
                self.i += 1
            elif self.peek() != "]":
                raise SnbtError("',' or ']' expected", self.i)
        self.i += 1
        return out


def parse_compound(text: str) -> _Result:
    """Parse `text` as an SNBT compound. Raises SnbtError (a ValueError) if it is malformed."""
    reader = _Reader(text)
    if reader.peek() != "{":
        raise SnbtError("custom data must be a compound, starting with '{'", reader.i)
    value = reader.compound(0)
    if reader.peek():
        raise SnbtError("unexpected text after the closing '}'", reader.i)
    return _Result(value, reader.lossy)


def check_compound(text: str) -> str | None:
    """Error message for a malformed compound, None if it is fine."""
    try:
        parse_compound(text)
    except SnbtError as exc:
        return str(exc)
    return None
