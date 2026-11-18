"""The code must parse on every Python it says it runs on (pyproject: requires-python >= 3.11; the CloudFormation
template installs and starts it with python3.11).

Round-2 review B-I1: one line of agents/step_recorder.py put a backslash inside an f-string's replacement field.
That is legal from Python 3.12 (PEP 701) and a SyntaxError before — on 3.11 the module could not be imported, so no
diagnosis and no execution could run, and the suite (which runs on 3.12) never noticed.

On 3.12+ the tokenizer splits an f-string into its parts, so the three things PEP 701 newly allows inside a
replacement field can be found: a backslash, the enclosing quote reused, a comment. On 3.11 itself the same files
are simply compiled.
"""
import io
import sys
import tokenize
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src" / "agenticops"


def needs_312(source: str) -> list[str]:
    """Every place in `source` that only parses on Python 3.12+: (line, what)."""
    found, stack = [], []          # stack: the opening of each f-string we are inside (its quote, triple or not)
    for tok in tokenize.generate_tokens(io.StringIO(source).readline):
        if tok.type == tokenize.FSTRING_START:
            quote = tok.string.lstrip("rRfFbBuU")
            if stack and not stack[-1][1] and quote[0] == stack[-1][0]:
                found.append(f"{tok.start[0]}: the enclosing quote is reused inside a replacement field")
            stack.append((quote[0], len(quote) == 3))
        elif tok.type == tokenize.FSTRING_END:
            stack.pop()
        elif stack and tok.type != tokenize.FSTRING_MIDDLE:          # a token of a replacement field's expression
            if "\\" in tok.string:
                found.append(f"{tok.start[0]}: a backslash inside a replacement field")
            if tok.type == tokenize.COMMENT:
                found.append(f"{tok.start[0]}: a comment inside a replacement field")
            if tok.type == tokenize.STRING and not stack[-1][1] and tok.string.lstrip("rRbBuU")[0] == stack[-1][0]:
                found.append(f"{tok.start[0]}: the enclosing quote is reused inside a replacement field")
    return found


@pytest.mark.skipif(sys.version_info < (3, 12), reason="the tokenizer only splits f-strings from 3.12")
def test_the_scan_finds_what_only_312_parses():
    assert needs_312('x = f"{sub(r\'<\\\\/\\1\', text)}\\n"\n')                      # the line the review found
    assert needs_312('x = f"{d["key"]}"\n')
    assert needs_312('x = f"{value  # why\n}"\n')
    assert needs_312('x = f"{name}\\n" f\'{d["key"]}\' f"""{d["key"]}"""\n') == []   # all three are fine on 3.11


def test_every_source_file_parses_on_python_311():
    files = sorted(SRC.rglob("*.py"))
    assert len(files) > 200
    bad = []
    for path in files:
        source = path.read_text(encoding="utf-8")
        if sys.version_info >= (3, 12):
            bad += [f"{path.relative_to(SRC)}:{where}" for where in needs_312(source)]
        else:
            try:
                compile(source, str(path), "exec")
            except SyntaxError as e:
                bad.append(f"{path.relative_to(SRC)}:{e.lineno}: {e.msg}")
    assert bad == []
