"""Line-based data model for MIN3P ``.dat`` input files.

MIN3P input files are block-structured: a block opens with a single-quoted name
on its own line and closes with ``'done'``. Within a block, single-quoted
*sub-keywords* introduce zero or more positional data lines. A data line is a
whitespace-delimited list of value tokens with an optional trailing ``;comment``
that names the parameter(s) but is ignored by MIN3P itself.

The model here is deliberately *line-preserving*: every physical line of the
file is retained (including ``!`` comments and blank lines) so that a
read -> print round-trip reproduces the file value-for-value. The grouping of
data lines under their sub-keyword (used to address modifications) is a derived
view built with a schema vocabulary; because nothing is discarded, an incomplete
vocabulary never threatens round-trip fidelity -- it only limits which
parameters can be addressed by name.
"""

import re
from collections import OrderedDict

# A token is either a single-quoted string (which may contain spaces, e.g. a
# title or a Windows-style database path) or a run of non-whitespace characters.
_TOKEN_RE = re.compile(r"'[^']*'|\S+")


class Min3pBlockModificationError(Exception):
    """Raised when a modification targets a non-existent block coordinate."""
    pass


def normalise(text):
    """Return a canonical form of a block name or sub-keyword for matching.

    Strips surrounding single quotes, lowercases, and collapses internal
    whitespace to single spaces. Used both for block-name lookup keys and for
    matching sub-keywords against the schema vocabulary.

    Args:
        text: The raw text (with or without surrounding quotes).

    Returns:
        The normalised string.
    """
    text = text.strip()
    if len(text) >= 2 and text[0] == "'" and text[-1] == "'":
        text = text[1:-1]
    # Normalise en-/em-dashes to a hyphen: MIN3P block names use ' - ' as a
    # separator, but some files spell it with an en-dash ('control parameters –
    # variably saturated flow'). Treat them identically for matching.
    text = text.replace('–', '-').replace('—', '-')
    return re.sub(r'\s+', ' ', text).strip().lower()


def split_comment(code):
    """Split a raw line into (code, comment) at the first unquoted ``;``.

    The semicolon that begins a MIN3P inline comment must not be inside a
    single-quoted string (paths and titles never contain ``;`` in practice, but
    we respect quotes to be safe).

    Args:
        code: The raw line text (newline already stripped).

    Returns:
        Tuple ``(code_part, comment)`` where ``comment`` is the text after the
        ``;`` (without the ``;``) or ``None`` if the line has no inline comment.
    """
    in_quote = False
    for i, ch in enumerate(code):
        if ch == "'":
            in_quote = not in_quote
        elif ch == ';' and not in_quote:
            return code[:i], code[i + 1:]
    return code, None


def tokenise(code):
    """Split the code portion of a line into value tokens, preserving quotes.

    Args:
        code: The code portion of a line (inline comment already removed).

    Returns:
        List of token strings; single-quoted strings are kept intact as one
        token with their quotes.
    """
    return _TOKEN_RE.findall(code)


class Line:
    """A single physical line of a MIN3P input file.

    Attributes:
        kind: ``'content'`` (has value tokens), ``'comment'`` (``!`` line), or
            ``'blank'``.
        tokens: List of value token strings for content lines; else ``[]``.
        comment: Inline ``;comment`` text (without ``;``) for content lines that
            have one; else ``None``.
        raw: The verbatim original line text (newline stripped). Used to render
            comment/blank passthrough lines unchanged.
    """

    __slots__ = ('kind', 'tokens', 'comment', 'raw')

    def __init__(self, kind, tokens=None, comment=None, raw=''):
        self.kind = kind
        self.tokens = tokens if tokens is not None else []
        self.comment = comment
        self.raw = raw

    @classmethod
    def parse(cls, raw):
        """Classify and parse a raw line.

        Args:
            raw: The verbatim line text with the trailing newline removed.

        Returns:
            A ``Line`` instance.
        """
        stripped = raw.strip()
        if not stripped:
            return cls('blank', raw=raw)
        if stripped.startswith('!'):
            return cls('comment', raw=raw)
        code, comment = split_comment(raw)
        tokens = tokenise(code)
        if not tokens:
            # Line was only an inline comment (rare); treat as comment passthrough.
            return cls('comment', raw=raw)
        return cls('content', tokens=tokens, comment=comment, raw=raw)

    def render(self):
        """Render the line back to text (without trailing newline)."""
        if self.kind != 'content':
            return self.raw
        text = ' '.join(self.tokens)
        if self.comment is not None:
            # Re-attach the inline comment. Preserve a readable gap; the exact
            # column need not match the original.
            if text:
                text = f'{text}    ;{self.comment}'
            else:
                text = f';{self.comment}'
        return text

    @property
    def norm(self):
        """Normalised form if this content line is a single quoted token, else None.

        A sub-keyword or a block name is a lone single-quoted token on its line.
        """
        if self.kind == 'content' and len(self.tokens) == 1:
            tok = self.tokens[0]
            if len(tok) >= 2 and tok[0] == "'" and tok[-1] == "'":
                return normalise(tok)
        return None


class Min3pBlock:
    """A single MIN3P data block (``'name'`` ... ``'done'``).

    Attributes:
        name: Canonical (normalised) block name, used as the lookup key.
        opener: The ``Line`` holding the block-opening quoted name.
        body: Ordered list of ``Line`` objects strictly between opener and
            ``'done'`` (including any interleaved comment/blank passthrough
            lines).
        closer: The ``Line`` holding ``'done'``.
        contents: ``OrderedDict`` mapping sub-keyword -> list of data ``Line``
            objects, built by :meth:`group`. Data lines that precede the first
            recognised sub-keyword live under the synthetic key ``'_header'``.
            Repeated sub-keywords are disambiguated as ``name#2``, ``name#3`` ...
        keyword_lines: Mapping sub-keyword -> the ``Line`` that introduced it.
    """

    def __init__(self, name, opener, closer):
        self.name = name
        self.opener = opener
        self.body = []
        self.closer = closer
        self.contents = OrderedDict()
        self.keyword_lines = OrderedDict()
        self.vocab = set()

    def group(self, vocab):
        """(Re)build :attr:`contents` by grouping body data lines under sub-keywords.

        Args:
            vocab: A set/collection of normalised sub-keyword strings recognised
                for this block. A content line whose normalised form is in
                ``vocab`` starts a new group; other content lines are data lines
                of the current group.
        """
        self.vocab = set(vocab)
        self.contents = OrderedDict()
        self.keyword_lines = OrderedDict()
        current = '_header'
        self.contents[current] = []
        occurrences = {}

        for line in self.body:
            if line.kind != 'content':
                continue
            norm = line.norm
            if norm is not None and norm in vocab:
                key = norm
                if key in self.contents:
                    occurrences[norm] = occurrences.get(norm, 1) + 1
                    key = f'{norm}#{occurrences[norm]}'
                current = key
                self.contents[key] = []
                self.keyword_lines[key] = line
            else:
                self.contents[current].append(line)

        # Drop the synthetic header if the block starts with a sub-keyword and
        # has no leading data lines, to keep the view tidy.
        if current != '_header' and not self.contents['_header']:
            del self.contents['_header']

    def data_line(self, keyword, index=0):
        """Return the ``index``-th data ``Line`` under ``keyword``.

        Raises:
            Min3pBlockModificationError: If the keyword or index is absent.
        """
        try:
            return self.contents[keyword][index]
        except KeyError as exc:
            raise Min3pBlockModificationError(
                f"Block '{self.name}' has no sub-keyword '{keyword}'. "
                f"Available: {list(self.contents)}"
            ) from exc
        except IndexError as exc:
            raise Min3pBlockModificationError(
                f"Sub-keyword '{keyword}' in block '{self.name}' has "
                f"{len(self.contents[keyword])} data line(s); index {index} "
                f"is out of range."
            ) from exc

    def modify(self, keyword, value, token_pos=0, line_index=0):
        """Modify a value within the block.

        Args:
            keyword: The sub-keyword group to target (``'_header'`` for leading
                positional data lines).
            value: The new value. If a list, the whole data line's tokens are
                replaced; otherwise the single token at ``token_pos`` is set.
            token_pos: Index of the token to replace when ``value`` is scalar.
                Negative indices are supported (``-1`` = last token).
            line_index: Which data line under ``keyword`` to modify (for
                sub-keywords owning several data lines, e.g. ``'mineral input'``).
        """
        line = self.data_line(keyword, line_index)
        if isinstance(value, (list, tuple)):
            line.tokens = [str(v) for v in value]
        else:
            line.tokens[token_pos] = str(value)

    def add_keyword(self, name, data_lines=None):
        """Append a sub-keyword (and optional data lines) to the end of the block.

        The new lines are inserted just before the ``'done'`` terminator (i.e.
        appended to :attr:`body`), then :attr:`contents` is rebuilt with the
        block's stored vocabulary plus ``name`` so the new group is addressable.
        Idempotent: if ``name`` is already present, nothing is added.

        Args:
            name: Sub-keyword to add (without quotes); emitted single-quoted.
            data_lines: Optional list of token-lists to add as its data lines.

        Returns:
            The normalised keyword string that was added (or already present).
        """
        key = normalise(name)
        if key in self.contents:
            return key
        self.body.append(Line('content', tokens=[f"'{name}'"]))
        for tokens in (data_lines or []):
            self.body.append(Line('content', tokens=[str(t) for t in tokens]))
        self.vocab.add(key)
        self.group(self.vocab)
        return key

    def render(self):
        """Render the whole block back to a list of text lines (no newlines)."""
        out = [self.opener.render()]
        out.extend(line.render() for line in self.body)
        out.append(self.closer.render())
        return out
