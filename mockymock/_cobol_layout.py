"""Where mocky-mock gets cobol-parser's record-layout offsets from.

Every other layout name (``ProgramLayoutIndex``, ``DataGeneratorOptions``,
``flatten_record``, ``ValueFactory``, ...) is imported from the package
``cobolparser.generators.data``, which still exports it. The two offset
functions are not re-exported there: since cobol-parser 4.0 (the floor)
they live in ``cobolparser.layout`` (#451), and their 3.x module
``generators.data.layout_offsets`` is gone.
"""

from __future__ import annotations

from cobolparser.layout import (
    compute_program_data_items,
    compute_record_layout,
)

__all__ = ["compute_program_data_items", "compute_record_layout"]
