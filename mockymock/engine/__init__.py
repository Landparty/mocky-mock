"""The engine: everything between the CLI and the pipeline packages.

`checks` runs the static checks every command starts with, and `build`
turns a checked program and suite into one instrumented program. The
interface layer (`cli`, `debug`, `web`) and the features (`mutation`,
`jobstream`, the report builder) call into here; nothing here imports
them. See `.okf/index.md` for the layering and
`tests/unit/test_layering.py` for its guard."""
