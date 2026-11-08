"""USE AFTER EXCEPTION/ERROR procedures (DECLARATIVES), for mocked file I/O.

A real file statement that ends in an exception condition (a FILE STATUS
not starting with "0") runs the USE procedure that applies to its file,
unless the statement has the phrase that handles that condition itself
(AT END for a "1x" status, INVALID KEY for a "2x"). A mocked statement
never reaches the runtime, so the splicer does what the runtime would:
after the mock it PERFORMs the applicable USE section when the mocked
outcome is such an exception (`splicer.orchestrator`, `use_clause`).

Which procedure applies (ISO 2002 14.10.47, IBM Enterprise COBOL):

- a USE naming the file itself (`USE AFTER ERROR PROCEDURE ON IX-FS2`);
- otherwise the one for the mode the file is open in (`ON INPUT`,
  `OUTPUT`, `I-O`, `EXTEND`). For an OPEN that is the mode it names; for
  any other statement the mode of the last OPEN, which the spliced OPENs
  record at run time in a `UT-OPEN-MODE-<n>` field per file
  (`mode_field`), since one file can be opened in several modes.

USE FOR DEBUGGING procedures run only when the runtime's debugging switch
is on (`COB_SET_DEBUG`, IBM's object-time DEBUG option); test binaries run
with it off (`runtime.executor.test_binary_env`), as production does, so
they never run. USE BEFORE REPORTING (Report Writer, whose verbs are
mocked whole) still refuses: `unsupported_use`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: An open mode -> the one-character code a `UT-OPEN-MODE-<n>` field holds.
MODE_CODES: dict[str, str] = {"INPUT": "I", "OUTPUT": "O", "I-O": "U", "EXTEND": "E"}

#: The guard (on `UT-MOCK-STATUS`, `clause_bodies.OUTCOME_FIELD`) that
#: selects the USE procedure: an exception outcome. The statement's own AT
#: END / INVALID KEY guards come first in the same `EVALUATE TRUE`, so a
#: condition its phrase handles never reaches this one.
USE_GUARD = 'UT-MOCK-STATUS NOT = SPACES AND UT-MOCK-STATUS(1:1) NOT = "0"'

_EXCEPTION_KINDS = frozenset({"EXCEPTION", "ERROR"})


@dataclass(frozen=True)
class UseProcedures:
    """The program's USE AFTER EXCEPTION/ERROR procedures.

    `by_file`: uppercased file name -> section, for a USE naming the file.
    `by_mode`: open mode -> section. `record_files`: uppercased FD record
    name -> its file (WRITE/REWRITE name the record). `files`: every
    file name of a SELECT, sorted (the `UT-OPEN-MODE-<n>` numbering)."""

    by_file: dict[str, str] = field(default_factory=dict)
    by_mode: dict[str, str] = field(default_factory=dict)
    record_files: dict[str, str] = field(default_factory=dict)
    files: tuple[str, ...] = ()
    #: Every paragraph and section name inside DECLARATIVES: a file
    #: statement there runs no USE procedure (the runtime does not re-enter
    #: a declarative from itself).
    declarative_names: frozenset[str] = frozenset()

    def file_of(self, key: str) -> str:
        """The file a site key names: the key itself, or a record's file."""
        key = key.upper()
        return self.record_files.get(key, key)

    def mode_field(self, file_name: str) -> str | None:
        """The field the spliced OPENs record `file_name`'s open mode in, or
        None when its procedure does not depend on the mode (a USE names
        the file, or no USE names any mode)."""
        file_name = file_name.upper()
        if file_name in self.by_file or not self.by_mode:
            return None
        if file_name not in self.files:
            return None
        return f"UT-OPEN-MODE-{self.files.index(file_name) + 1}"

    def mode_fields(self) -> list[tuple[str, str]]:
        """(file, field) for every file whose open mode is recorded."""
        return [
            (name, field_name)
            for name in self.files
            if (field_name := self.mode_field(name)) is not None
        ]

    def sections_for(self, file_name: str) -> list[str]:
        """Every USE section that can run for `file_name`, for the
        reachability walk."""
        file_name = file_name.upper()
        if file_name in self.by_file:
            return [self.by_file[file_name]]
        return list(dict.fromkeys(self.by_mode.values()))

    def perform_lines(self, file_name: str, open_mode: str | None) -> list[str]:
        """The statements that run `file_name`'s USE procedure after a
        mocked statement. `open_mode` is the mode an OPEN names (known
        statically); for any other statement the recorded mode decides.
        Empty when no procedure applies."""
        file_name = file_name.upper()
        if file_name in self.by_file:
            return [f"PERFORM {self.by_file[file_name]}"]
        if open_mode is not None:
            section = self.by_mode.get(open_mode.upper())
            return [f"PERFORM {section}"] if section else []
        mode_field = self.mode_field(file_name)
        if mode_field is None:
            return []
        lines = [f"EVALUATE {mode_field}"]
        for mode, section in self.by_mode.items():
            lines.append(f'    WHEN "{MODE_CODES[mode]}"')
            lines.append(f"        PERFORM {section}")
        lines.append("END-EVALUATE")
        return lines


def _use_statements(program):
    """(section name, UseStatement) for every USE in a declarative section."""
    procedure = program.get_division("PROCEDURE")
    if procedure is None:
        return
    for name, section in getattr(procedure, "_sections", {}).items():
        if not name or not (
            getattr(section, "is_declarative", False)
            or section.get_metadata("declarative")
        ):
            continue
        for paragraph in section.paragraphs:
            for statement in paragraph.statements:
                if type(statement).__name__ == "UseStatement":
                    yield name, statement


def _select_files(program) -> list[str]:
    from mockymock.analysis.mock_surface import file_selects

    return sorted(file_selects(program))


def use_procedures(program) -> UseProcedures | None:
    """The program's USE AFTER EXCEPTION/ERROR procedures, or None when it
    has none."""
    from mockymock.analysis.mock_surface import _fd_records

    files = _select_files(program)
    by_file: dict[str, str] = {}
    by_mode: dict[str, str] = {}
    for section, statement in _use_statements(program):
        if (statement.use_type or "").upper() not in _EXCEPTION_KINDS:
            continue
        for name in statement.file_names:
            word = str(name).upper()
            if word in MODE_CODES:
                by_mode.setdefault(word, section)
            else:
                by_file.setdefault(word, section)
    if not by_file and not by_mode:
        return None
    return UseProcedures(
        by_file=by_file,
        by_mode=by_mode,
        record_files=dict(_fd_records(program)),
        files=tuple(files),
        declarative_names=frozenset(declarative_paragraphs(program)),
    )


def unsupported_use(program) -> str | None:
    """Why the program's DECLARATIVES cannot run under mocks, or None.

    A USE BEFORE REPORTING runs before a Report Writer group is presented,
    and GENERATE is mocked whole; a USE AFTER with no file or mode could
    not be placed. Both stay refused (UNSUPPORTED_DECLARATIVES)."""
    files = set(_select_files(program))
    for section, statement in _use_statements(program):
        kind = (statement.use_type or "").upper()
        line = getattr(getattr(statement, "location", None), "line", None)
        if kind == "REPORTING":
            return (
                f"section '{section}' (line {line}) is a USE BEFORE REPORTING "
                f"procedure; Report Writer GENERATE is mocked whole, so it "
                f"would never run"
            )
        if kind in _EXCEPTION_KINDS:
            names = [str(name).upper() for name in statement.file_names]
            if not names:
                return (
                    f"section '{section}' (line {line}): the USE AFTER "
                    f"EXCEPTION procedure names no file or open mode the "
                    f"parser could read"
                )
            unknown = [n for n in names if n not in MODE_CODES and n not in files]
            if unknown:
                return (
                    f"section '{section}' (line {line}): the USE AFTER "
                    f"EXCEPTION procedure names '{unknown[0]}', which is no "
                    f"file of a SELECT"
                )
        elif kind != "DEBUGGING":
            return (
                f"section '{section}' (line {line}) holds a USE statement of "
                f"a kind mockymock does not know ({kind or 'none'})"
            )
    return None


def declarative_paragraphs(program) -> set[str]:
    """Every paragraph and section name inside DECLARATIVES."""
    procedure = program.get_division("PROCEDURE")
    names: set[str] = set()
    if procedure is None:
        return names
    for name, section in getattr(procedure, "_sections", {}).items():
        if name and (
            getattr(section, "is_declarative", False)
            or section.get_metadata("declarative")
        ):
            names.add(name)
            names.update(p.paragraph_name for p in section.paragraphs)
    return names
