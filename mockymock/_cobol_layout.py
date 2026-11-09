"""Where mocky-mock gets cobol-parser's record-layout offsets from.

Every other layout name (``ProgramLayoutIndex``, ``DataGeneratorOptions``,
``flatten_record``, ``ValueFactory``, ...) is imported from the package
``cobolparser.generators.data``, which exports it on 3.x and on main, where
the record layout moved to ``cobolparser.layout`` (#451). The two offset
functions are not re-exported there, so they are looked up in their new home
first and their 3.x module second.
"""

from __future__ import annotations

try:  # cobol-parser main (4.x): cobolparser.layout
    from cobolparser.layout import (
        compute_program_data_items,
        compute_record_layout,
    )
except ImportError:  # pragma: no cover - cobol-parser 3.x
    from cobolparser.generators.data.layout_offsets import (
        compute_program_data_items,
        compute_record_layout,
    )

__all__ = ["compute_program_data_items", "compute_record_layout"]
