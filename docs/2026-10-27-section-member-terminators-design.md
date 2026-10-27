# GOBACK / STOP RUN in SECTION members — Design

Date: 2026-10-27
Status: implemented

Extends [2026-07-10-section-scoped-terminator-support-design.md](2026-07-10-section-scoped-terminator-support-design.md),
which supported one shape only: a terminator in a section's *first*
paragraph, entered via `PERFORM <section-name>`. That left the most common
mainframe layout refused: the whole program in one `MAIN SECTION`, its
paragraphs PERFORMed by name, `GOBACK` at the end of the first one. A
sweep over a real corpus refused 59 programs this way, typically with
"inside a paragraph that belongs to a SECTION" or "SECTION-scoped chains
are not yet supported".

## The rule: one entry mode per member

What decides which EXIT verb returns correctly from a paragraph is the
PERFORM range it runs in, not where it sits in the source:

* **Section mode.** It runs inside a `PERFORM <section-name>` range: the
  section's first paragraph, and each later member reached by falling
  through from one that does not provably divert (`_falls_through`: last
  statement GOBACK / STOP RUN / a plain GO TO / EXIT PARAGRAPH-SECTION-
  PROGRAM / EXEC CICS RETURN). Its terminator, and the flag check after
  each chain PERFORM it holds, use `EXIT SECTION`.
* **Paragraph mode.** It is only ever PERFORMed by its own name, so its
  range is the paragraph alone. Its terminator and checks use `EXIT
  PARAGRAPH`, exactly like a top-level paragraph.

`refusal._section_member_modes(program, paragraph_entries,
section_entries)` assigns each member one mode from the whole program's
PERFORM statements (any kind, conditional or looping) plus every case's
own PERFORM target. A member gets **no** mode, and its terminators stay
refused, when it is:

* entered both ways (e.g. one case PERFORMs the section, another its first
  paragraph);
* inside any `PERFORM ... THRU` range (section endpoints expand to their
  first / last member);
* a GO TO target (written, EXEC SQL WHENEVER, CICS HANDLE label), or in a
  section that is one;
* a name defined in more than one section.

A section's nameless main line (and phantom `.` nodes) can only be in
section mode. When a THRU range cannot be expanded, the result falls back
to the 2026-07-10 rule.

`_plain_perform_edges_from(..., member_modes)` follows a `PERFORM
<section>` into every section-mode member and a `PERFORM <member>` into a
paragraph-mode one; everything else still dead-ends and refuses.

## Verified against GnuCOBOL 3.2 (`-free -std=mvs`)

| Shape | Result |
|---|---|
| Member PERFORMed by name, conditional terminator → `MOVE "Y"` + `EXIT PARAGRAPH`; caller's check `EXIT PARAGRAPH` | returns; the next member does not run; repeatable |
| `PERFORM S`, terminator in a later member reached by fall-through → `EXIT SECTION` | returns; later member does not run |
| `PERFORM S`, chain PERFORM in a fallen-into member, check `EXIT SECTION`, callee in another section PERFORMed by name with `EXIT PARAGRAPH` | returns; nothing after runs |

Pinned end to end by `tests/integration/test_terminator_support.py`
(`test_terminators_in_section_members_return_to_the_driver`,
`test_terminator_in_an_exit_paragraph_reached_by_fall_through`) and in
unit tests by `tests/unit/test_terminators.py`.

## Not changed

`generate` still PERFORMs a program's first paragraph (or its section when
the main line has no paragraph name, issue #238). PERFORMing the section
instead would also run the paragraphs a real run falls into; that is a
separate scaffold decision.
