from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import *
import logging
import re

from ruamel.yaml import YAML
import yaml as pyyaml

log = logging.getLogger(__name__)

ch = logging.StreamHandler()
ch.setLevel(logging.DEBUG)
ch.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
log.addHandler(ch)

config = {
    "double_check": True,
    "fix_in_place": False,
}

INDENT_WITH = " " * 2


class YamlError(Exception):
    pass


class TokenError(YamlError):
    pass


class ParseError(YamlError):
    pass


class SanitizeError(YamlError):
    pass


@dataclass
class Token:
    type_: str
    line: int
    column: int
    value: Optional[str] = None


_tag_re = re.compile(r"!!(\S*)").match
_value_re = re.compile(r'"(.*?)(?<!\\)"', re.DOTALL).match
_comment_re = re.compile(r" ?#(.*)").match


def tokenize(yaml: str) -> Sequence[Token]:
    line = col = ws = 1
    while yaml:
        # insignificant markers
        if yaml[:1] in ("\n", " ", ","):
            if yaml[0] == "\n":
                if ws == col:
                    yield Token("empty-line", line=line, column=col)
                line += 1
                col = ws = 1
            elif yaml[0] == " ":
                col += 1
                ws += 1
            else:
                col += 1
            yaml = yaml[1:]
            continue

        if yaml[:3] == "---":
            yield Token("document", line=line, column=col)
            yaml = yaml[3:]
            col += 3
            continue

        # map
        if yaml.startswith("{"):
            yield Token("map-open", line=line, column=col)
            yaml = yaml[1:]
            col += 1
            continue
        if yaml.startswith("}"):
            yield Token("map-close", line=line, column=col)
            yaml = yaml[1:]
            col += 1
            continue
        if yaml.startswith("?"):
            yield Token("map-key", line=line, column=col)
            yaml = yaml[1:]
            col += 1
            continue
        if yaml.startswith(":"):
            yield Token("map-val", line=line, column=col)
            yaml = yaml[1:]
            col += 1
            continue

        # seq
        if yaml.startswith("["):
            yield Token("seq-open", line=line, column=col)
            yaml = yaml[1:]
            col += 1
            continue
        if yaml.startswith("]"):
            yield Token("seq-close", line=line, column=col)
            yaml = yaml[1:]
            col += 1
            continue

        _tag = _tag_re(yaml)
        if _tag:
            yield Token("tag", value=_tag[1], line=line, column=col)
            yaml = yaml[_tag.end() :]
            col += _tag.end()
            ws += _tag.end()
            continue

        _value = _value_re(yaml)
        if _value:
            yield Token(
                "value", value=_value[1].replace("\\\n\\", ""), line=line, column=col
            )
            yaml = yaml[_value.end() :]
            col += _value.end()
            continue

        _comment = _comment_re(yaml)
        if _comment:
            yield Token(
                "comment-line" if ws == col else "comment-inline",
                value=_comment[1],
                line=line,
                column=col,
            )
            yaml = yaml[_comment.end() :]
            col += _comment.end()
            continue

        raise TokenError(f"Found garbage: {line}:{col}: {yaml[:20]}...")


def yaml_int(s: str) -> str:
    if s.startswith("0o"):
        return oct(int(s, 8))
    if s.startswith("0x"):
        return hex(int(s, 16))
    return repr(int(s))


def yaml_str(s: str) -> str:
    if "\\" in s or "'" in s:
        return f'"{s}"'
    s = s.replace("'", "''")
    return f"'{s}'"


_is_obvious_mapping_key = re.compile(r"[_a-zA-Z0-9]+$").fullmatch


def yaml_mapping_key(s: str) -> str:
    return s if _is_obvious_mapping_key(s) else yaml_str(s)


def normalize_scalar(type_: str, value: str) -> str:
    """Turn scalar value strings into sensible YAML representations.

    Uses canonicalized untagged representations for
    - bool
    - float
    - int
    - null
    - str
    """
    typemap = {
        # "bool": lambda s: "true" if s == "true" else "false",
        "float": lambda s: repr(float(s)),
        "int": yaml_int,
        "null": lambda _: "null",
        "str": yaml_str,
    }
    return typemap[type_](value) if type_ in typemap else value


def clean_comment(commentval: str) -> str:
    c = commentval.rstrip()
    if c.startswith("#") or c.startswith(" "):
        return f"#{c}"
    return f"# {c}"


def normalize(yaml: str) -> str:
    """Return the given canonical YAML string in our normalized form.

    This function could just as well be called "canonicalize", but to avoid
    confusion between the YAML spec/parser's canonical representation and ours,
    we opt for "normalize".  The point is: We reformat everything. Hard.
    """
    scalars = {"bool", "float", "int", "null", "str"}
    collections = {"map", "seq"}
    printables = {
        "comment-inline",
        "comment-line",
        "empty-line",
        "tag",
        "value",
    }

    formatted = ""
    one_doc = False
    next_value_is_map_key = False
    next_value_is_map_val = False
    prev_printable = prev = Token("none", 0, 0)

    stack: List[str] = []

    for tok in tokenize(yaml):
        level = len(stack)
        coll: Optional[str] = stack[-1] if level > 0 else None
        indent = (level - 1) * INDENT_WITH
        newline = "\n"

        log.debug(f"{level}: {tok}")

        if tok.type_ == "document":
            if one_doc is True:
                raise SanitizeError(f"Only one document allowed per file: {tok}")
            one_doc = True

        # format & print the structure
        elif tok.type_ == "tag":
            if tok.value not in collections | scalars:
                raise SanitizeError(f"Tag not allowed: {tok}")

            if tok.value in collections:
                stack.append(tok.value)

            if next_value_is_map_val:
                next_value_is_map_val = False
                indent = " " if tok.value in scalars else ""
                newline = ""
            elif not formatted:
                newline = ""

            formatted += newline + indent

            if coll == "seq":
                formatted += "- "

        # format & print the output value
        elif tok.type_ == "empty-line":
            if formatted and prev_printable.type_ != "empty-line":
                formatted += newline
        elif tok.type_ == "comment-line":
            if formatted:
                formatted += newline
            formatted += indent + clean_comment(tok.value)
        elif tok.type_ == "comment-inline":
            formatted += "  " + clean_comment(tok.value)
        elif tok.type_ == "value":
            if prev.type_ != "tag":
                raise ParseError(f"Unexpected value: {tok}")

            if not next_value_is_map_key:
                formatted += normalize_scalar(prev.value, tok.value)
            else:
                next_value_is_map_key = False
                if prev.value != "str":
                    raise SanitizeError(
                        f"Only strings are allowed as mapping keys, got: {prev}"
                    )
                formatted += yaml_mapping_key(tok.value) + ":"

        # seq
        elif tok.type_ == "seq-close":
            if prev.type_ == "seq-open":
                formatted += " []"
            stack.pop()

        # map
        elif tok.type_ == "map-close":
            if prev.type_ == "map-open":
                formatted += " {}"
            stack.pop()
        elif tok.type_ == "map-val":
            next_value_is_map_val = True
        elif tok.type_ == "map-key":
            if next_value_is_map_key:
                raise ParseError(f"Unexpected map key: {tok}")
            next_value_is_map_key = True

        # prepare next iteration
        if not tok.type_.startswith("comment-"):
            # ignore comments because they don't affect our state
            prev = tok
        if tok.type_ in printables:
            prev_printable = tok

    if one_doc is False:
        raise ParseError("No document found.")

    return formatted + "\n"


def normalized(path: Path) -> str:
    yaml = YAML(typ="rt", pure=True)
    data = yaml.load(path)
    yaml.canonical = True
    canonical = StringIO("")
    yaml.dump(data, canonical)
    canonical = canonical.getvalue()
    log.debug(canonical)
    return normalize(canonical)


def redump(yaml: str) -> str:
    return pyyaml.safe_dump(pyyaml.safe_load(yaml))


def usage():
    print(
        """Usage: yamill [options] <paths ...>

Options:
  --debug   Output debugging information. (extremely verbose)
  --fix     Fix files in place.
  --unsafe  Speed up processing when writing back fixed files by skipping
            checks to ensure the data did not change.  DO NOT USE!
"""
    )


def cli(args) -> int:
    if not args or "--help" in args:
        usage()
        return 1 if not args else 0
    if "--debug" in args:
        log.setLevel(logging.DEBUG)
    if "--unsafe" in args:
        config["double_check"] = False
    if "--fix" in args:
        config["fix_in_place"] = True

    paths = (Path(arg) for arg in args if not arg.startswith("--"))

    checked = needs_change = changed = 0
    for path in paths:
        current = path.read_text()
        fixed = normalized(path)
        log.debug(fixed)
        checked += 1
        if current != fixed:
            needs_change += 1
            if not config["fix_in_place"]:
                print(f"would reformat {path}")
            else:
                if config["double_check"] and redump(current) != redump(fixed):
                    print(f"Oh my, failed to reformat {path}! 🐛 😱 🐛")
                    print("Please report this as a bug!")
                else:
                    path.write_text(fixed)
                    changed += 1
                    print(f"reformatted {path}")
    if needs_change != changed:
        print("Oh no! 💥 💔 💥")
        print(f"{needs_change - changed} files still need to be reformatted. 🌩")
        return 1
    print("All done! ✨ 🍰 ✨")
    print(f"{changed} files reformatted. ⚡️" if changed else "No files changed. 😴")
    return 0


def main():
    import sys

    sys.exit(cli(sys.argv[1:]))


if __name__ == "__main__":
    main()
