"""Reading and parsing of MIN3P ``.dat`` template files."""

import copy

import numpy as np

from min3p.input_file import InputFile
from min3p.keyword_block import Line, Min3pBlock, normalise
from min3p.schema import vocab_for


def _opener_name(line):
    """Return the normalised block name if ``line`` opens a block, else None.

    A block opener is a content line whose first token is a single-quoted string
    (the block name; a trailing inline comment may follow) and whose name is not
    the ``'done'`` terminator. This deliberately rejects un-commented banner
    text, stray titles, and orphan ``'done'`` lines so they are preserved as
    passthrough rather than mistaken for blocks.
    """
    if line.kind != 'content' or not line.tokens:
        return None
    tok = line.tokens[0]
    if len(tok) >= 2 and tok[0] == "'" and tok[-1] == "'":
        name = normalise(tok)
        if name != 'done':
            return name
    return None


class Template(InputFile):
    """An :class:`InputFile` built by parsing a MIN3P ``.dat`` template.

    Block detection needs no schema: MIN3P blocks never nest and always close
    with ``'done'``, so the block opener is simply the first content line after
    each terminator. The schema vocabulary is used only afterwards, to group
    each block's data lines under their sub-keywords for addressable
    modification.
    """

    def __init__(self, config):
        self.config = config
        elements, keyword_blocks, newline = self.read_file(config['template'])
        super().__init__(config['template'], elements, keyword_blocks, newline=newline)
        self.later_inputs = {}
        self.error_code = 0

        # Group each block's data lines under its recognised sub-keywords.
        for block in self.keyword_blocks.values():
            block.group(vocab_for(block.name))

    @staticmethod
    def read_file(path):
        """Parse a MIN3P ``.dat`` file.

        Args:
            path: Path to the ``.dat`` file.

        Returns:
            Tuple ``(elements, keyword_blocks, newline)``:

            - ``elements``: ordered list of ``Line`` (passthrough) and
              ``Min3pBlock`` objects reproducing the whole file.
            - ``keyword_blocks``: dict of normalised block name -> ``Min3pBlock``
              (same objects as in ``elements``; duplicates suffixed ``#2`` ...).
            - ``newline``: detected line terminator (``'\\r\\n'`` or ``'\\n'``).
        """
        with open(path, 'r', newline='', errors='replace') as f:
            raw = f.read()

        newline = '\r\n' if '\r\n' in raw else '\n'
        raw_lines = raw.split('\n')
        # A trailing newline yields a final empty element from split(); drop it
        # so we don't emit a spurious blank line on write.
        if raw_lines and raw_lines[-1] == '':
            raw_lines.pop()

        elements = []
        keyword_blocks = {}
        block_counts = {}
        current_block = None

        for raw_line in raw_lines:
            line = Line.parse(raw_line.rstrip('\r'))

            if current_block is None:
                # A MIN3P block opener is always a single-quoted keyword whose
                # first token is that quoted name (a trailing inline comment may
                # follow). Anything else outside a block -- comments, blanks, an
                # un-commented banner, a stray title, or an orphan 'done' -- is
                # preserved verbatim as passthrough rather than mistaken for a
                # block (which would swallow the real block that follows).
                opener_name = _opener_name(line)
                if opener_name is not None:
                    current_block = Min3pBlock(opener_name, opener=line, closer=None)
                    elements.append(current_block)
                else:
                    elements.append(line)
            else:
                if line.kind == 'content' and line.norm == 'done':
                    current_block.closer = line
                    # Register the completed block, disambiguating duplicates.
                    key = current_block.name
                    if key in keyword_blocks:
                        block_counts[current_block.name] = block_counts.get(current_block.name, 1) + 1
                        key = f'{current_block.name}#{block_counts[current_block.name]}'
                    keyword_blocks[key] = current_block
                    current_block = None
                else:
                    current_block.body.append(line)

        if current_block is not None:
            raise ValueError(
                f"Unterminated block '{current_block.name}' in {path}: "
                f"reached end of file without a 'done' line."
            )

        return elements, keyword_blocks, newline

    def make_dict(self):
        """Return a dict ``{file_num: InputFile}`` of deep copies of this template.

        Deep-copying the whole ``InputFile`` preserves the shared references
        between ``elements`` and ``keyword_blocks`` (and, within a block, between
        ``contents`` and ``body``), so a modification made via ``keyword_blocks``
        is reflected when the file is printed from ``elements``.
        """
        file_dict = dict.fromkeys(np.arange(self.config['number_of_files']))
        for file_num in file_dict:
            new_file = copy.deepcopy(
                InputFile(self.config['template'], self.elements, self.keyword_blocks, self.newline)
            )
            new_file.file_num = int(file_num)
            file_dict[file_num] = new_file
        return file_dict
