# Changelog

## Unreleased

### Added

- `mockymock fixtures <program> [--scenarios happy|branches|all] [--seed N] [--rows N] [--copybook-path DIR]...` — new subcommand: prints a cobolparser `FixtureBundle` (scenarios, seeded mock data, expectations) as JSON on stdout, for editor integrations. No Docker dependency; stdout is JSON only, all diagnostics go to stderr.
- `mockymock generate --with-data --rows N` — seeds the self-generating fixture bundle's row count (`--rows 0` is honored, not treated as falsy). Rejected with a stderr error and exit 1 when combined with `--fixtures`, whose row count is already baked into the checked-in bundle.
- `mockymock generate --placeholder CATEGORY:KEY` (repeatable; valid with either `--with-data` or `--fixtures`) — downgrades a matched fixture's mock body to its ordinary non-data placeholder while keeping it mocked; a malformed value (no `:`) exits 1, an unmatched pair warns on stderr. A downgraded loop-bearing boundary (a multi-row `READ`, a multi-row `SQL ... ROWS` cursor fetch) keeps real loop-termination semantics instead of silently hanging, and its tier-1 `VERIFY ... WAS CALLED n TIMES` is recomputed to match the downgraded body's actual call count (or demoted to a `*>` comment when that count isn't knowable by construction).
- `.cut` DSL: `ROWS` now applies to `MOCK READ <file> ROWS` (previously `MOCK SQL "..." ROWS` only), with an optional READ-only `TERMINAL ( FIELD = value, ... )` group for the rows-exhausted branch. Hand-authoring grammar only — the bundle-driven `generate --with-data`/`--fixtures` scaffold does not emit it.

### Changed

- `refusal.check_test_case` gained a second `UNRESOLVED_FILE_STATUS_TARGET` trigger: a `MOCK READ ... ROWS` mock with neither its own `TERMINAL` group nor a declared `FILE STATUS` field on that file now refuses fail-closed instead of generating a read loop with no way to terminate.
- `splicer/injector.build_rows_block` generalized from a SQL-only function that hardcoded SQLCODE 0/100 to `build_rows_block(tally_name, rows, *, row_suffix_moves, exhausted_moves)`, with the SQLCODE literals moved to their SQL call site in `build_site_dispatch` and a new READ call site alongside it.
- Bumped the vendored `cobolparser` pin to `ff64b25` (includes upstream PR #110's gen-fixtures fixes and PR #112's EJECT support).

## [0.5.0](https://github.com/samdion1994/mocky-mock/compare/v0.4.0...v0.5.0) (2026-08-07)


### Features

* add mockymock analyze passthrough to cobol-parser's CLI ([f43dc11](https://github.com/samdion1994/mocky-mock/commit/f43dc117bbf132dc2e79b67552c295fe378ac92c))
* **refusal:** narrow PARSE_WARNING/UNRESOLVED_COPYBOOK to paragraph scope ([ac17f9e](https://github.com/samdion1994/mocky-mock/commit/ac17f9e2f0b92273ca460cfaa0b768fb7bda5b95))


### Bug Fixes

* **mutation:** propagate scoped-refusal waiver notes through mutate ([cbcc6f9](https://github.com/samdion1994/mocky-mock/commit/cbcc6f929dc376ae282365171645ba61f501d9cc))
* **refusal:** add independent safety net for PARSE_WARNING line trust ([0260ea5](https://github.com/samdion1994/mocky-mock/commit/0260ea5b6468fe97e6fbb2a345ee1c4528a38ccf))
* **refusal:** verify a waivable COPY's span textually, not via PERIOD tokens ([7d3ce74](https://github.com/samdion1994/mocky-mock/commit/7d3ce74690abff17770f52c526d639707fcd5712))
* update second stale INVOKE fixture, drop dangling unused import ([bf1cabd](https://github.com/samdion1994/mocky-mock/commit/bf1cabd818662d997549d346756bd6cd3cbebf8b))
* update stale INVOKE unsupported-verb fixture to EXHIBIT ([6eabb5f](https://github.com/samdion1994/mocky-mock/commit/6eabb5fe42f88c1238e6c3fc63028380d0db13a3))

## [0.4.0](https://github.com/samdion1994/mocky-mock/compare/v0.3.0...v0.4.0) (2026-08-06)


### Features

* **cli:** --rows and --placeholder on generate --with-data (Task 4) ([8799281](https://github.com/samdion1994/mocky-mock/commit/879928121d2afc8eea1df4d6a0fd03490c5bb336))
* **cli:** add generate --with-data for bundle-driven .cut scaffolding ([19c2986](https://github.com/samdion1994/mocky-mock/commit/19c29866c9c2c72b458b85b66090caae9b7dfada))
* **cli:** add run --record-expectations for golden/characterization testing ([acb1663](https://github.com/samdion1994/mocky-mock/commit/acb1663ad97071e82609853b3f9884307fe495fb))
* **cli:** hand-port the `mockymock fixtures` subcommand ([c2ab4a8](https://github.com/samdion1994/mocky-mock/commit/c2ab4a86d6155dcd8c24e625dd87d568fa8e4c6f))
* **cli:** record-expectations golden mode + generate --with-data (gen-fixtures Phases 7b/8) ([e87c027](https://github.com/samdion1994/mocky-mock/commit/e87c0273351bb59b78cd04c7e3068b95d92088b2))
* **dsl:** ROWS on MOCK READ with optional TERMINAL group ([fce3f04](https://github.com/samdion1994/mocky-mock/commit/fce3f04246eb3b64c6c7093debd6a7a610c22bdc))
* **splicer:** READ ROWS dispatch with terminal branch + fail-closed refusal ([40ecbad](https://github.com/samdion1994/mocky-mock/commit/40ecbad9c99e99e140df4b49fd0bc3b45f3490cb))


### Bug Fixes

* **cli:** fixtures runs the same fail-closed gates as generate ([d0006b6](https://github.com/samdion1994/mocky-mock/commit/d0006b6255abc20c551c6d6ff1ad43b392e4c80d))
* **docs/tests:** fold in review round 1 findings for Task 5 ([07a8fbc](https://github.com/samdion1994/mocky-mock/commit/07a8fbc4db0128becd0eced97a38633f2dd433b0))
* **dsl:** preserve READ/SQL-ROWS loop-termination through --placeholder/--rows 0 ([8ccb590](https://github.com/samdion1994/mocky-mock/commit/8ccb590bad9be7eb8bbb7dd59cd4d3eaf705ed84))
* **dsl:** recompute VERIFY call_count for a downgraded loop-bearing boundary ([427474a](https://github.com/samdion1994/mocky-mock/commit/427474a2259d1e08ab0716635586749609494d77))
* **dsl:** replicate READ's AT END clause to prevent infinite loops ([3ad3378](https://github.com/samdion1994/mocky-mock/commit/3ad3378c76a6a764e70a3afb7202254129dea94d))
* **review:** PR [#46](https://github.com/samdion1994/mocky-mock/issues/46) post-review polish pass ([53669b4](https://github.com/samdion1994/mocky-mock/commit/53669b4b3f66f13fbbf0e3938b1184e72a693772))


### Documentation

* **plan:** record cobolparser pin amendment to ff64b25 (Task 1) ([957c4d9](https://github.com/samdion1994/mocky-mock/commit/957c4d9ed5ef7b943aa38b77efe424bb653e08b1))
* reconciliation plan -- port branch deliverables onto main's engine ([bc84332](https://github.com/samdion1994/mocky-mock/commit/bc8433270f35f69b81e9bb413440efe6551a2b29))
* **splicer:** note READ ROWS terminal resolution and the fail-closed guard's production invariant ([4463bf0](https://github.com/samdion1994/mocky-mock/commit/4463bf0a53dfbfae1c375e705e565566c7680351))

## [0.3.0](https://github.com/samdion1994/mocky-mock/compare/v0.2.0...v0.3.0) (2026-08-04)


### Features

* **cli:** add column-restoration and provenance-header helpers for mainframe export ([050e418](https://github.com/samdion1994/mocky-mock/commit/050e41870d2621ef95b114e763d9e23a85f41e4d))
* **cli:** add mockymock export for real fixed-format (z/OS) COBOL compiles ([60b19cf](https://github.com/samdion1994/mocky-mock/commit/60b19cf1c0a4ac15a183f25a134a735ef8aa52d7))
* **cli:** add mockymock export subcommand ([9437fd4](https://github.com/samdion1994/mocky-mock/commit/9437fd436d884496399cc048058fe1d3176b0674))
* **cli:** add preserve_compiler_directives option to run_static_checks ([3ccbc6b](https://github.com/samdion1994/mocky-mock/commit/3ccbc6be7ac6e83864f9a029895c8bd58cd59b64))
* **cli:** wrap over-72-column generated DISPLAY statements for mainframe export ([44a52a5](https://github.com/samdion1994/mocky-mock/commit/44a52a504c65efc6240a6a347233cd4bf6407fe9))


### Bug Fixes

* **cli:** address final whole-branch review findings for export ([5b125d1](https://github.com/samdion1994/mocky-mock/commit/5b125d159ef81ad4cd89d42cc48de2c68404b436))
* **cli:** clarify why the not-tail safety net isn't dead code ([b164e91](https://github.com/samdion1994/mocky-mock/commit/b164e910cb53428ee3decb01bda71fd5260b59fb))
* **cli:** rename ambiguous loop variable to satisfy ruff E741 ([2e124d3](https://github.com/samdion1994/mocky-mock/commit/2e124d3b4ae7b0f0a437f079b11b740f2983e61d))
* **tests:** stop hardcoding version in test_mockymock_has_a_version ([e50882a](https://github.com/samdion1994/mocky-mock/commit/e50882a83c30d92252e70023eb3f9d7cd46af013))


### Documentation

* add mainframe (z/OS) export command design ([a2dd00a](https://github.com/samdion1994/mocky-mock/commit/a2dd00a6c85c16c898c63847297a8476a3203b6d))
* correct stale algorithm claims after chunking redesign ([d79accc](https://github.com/samdion1994/mocky-mock/commit/d79accc363c39c2738fe44f78d0aa8d39d465f74))
* document mockymock export in the OKF bundle and README ([6bf9685](https://github.com/samdion1994/mocky-mock/commit/6bf9685e0a6ca8f33a8121c643a10740f38c4cdd))
* revise export command design after empirical column spike ([bf2de7f](https://github.com/samdion1994/mocky-mock/commit/bf2de7f67f86f504e0dcc0aeb4bb68294082884d))

## [0.2.0](https://github.com/samdion1994/mocky-mock/compare/v0.1.1...v0.2.0) (2026-08-03)


### Features

* **cli:** add `mockymock dashboard`, a local toolchain status page ([ff151e5](https://github.com/samdion1994/mocky-mock/commit/ff151e578c79ccaa4dcb2afd01d85b75b5a49b84))
* **cli:** add `mockymock dashboard`, a local toolchain status page ([557d0a8](https://github.com/samdion1994/mocky-mock/commit/557d0a8a6185a2b388b4f5b11d956412f124c9e4))


### Documentation

* **okf:** document the v0.1.0 asset-loss/v0.1.1 recovery and its two root causes ([d03f634](https://github.com/samdion1994/mocky-mock/commit/d03f634569adb35734a38ffff74a4e4d5162a36b))

## [0.1.1](https://github.com/samdion1994/mocky-mock/compare/v0.1.0...v0.1.1) (2026-08-03)


### Bug Fixes

* **release:** remove stale release-as pin from release-please-config ([2c08bd2](https://github.com/samdion1994/mocky-mock/commit/2c08bd2187ccb18fbcf19bf2069e3ee7c69cdadf))


### Miscellaneous Chores

* force a release to ship v0.1.0's CI-fixed binaries ([02a5246](https://github.com/samdion1994/mocky-mock/commit/02a524633f163bf6ab671ed25300e2e0e4422ee7))

## 0.1.0 (2026-08-03)


### ⚠ BREAKING CHANGES

* remove local cobc toolchain; all compile/run goes through Docker

### Features

* .cut DSL model and parser ([7ef2fbc](https://github.com/samdion1994/mocky-mock/commit/7ef2fbc6c53996a8e3258ad0dc223630d0cc2674))
* .cut DSL parses PERFORM &lt;target&gt; THRU &lt;endpoint&gt; ([930ce61](https://github.com/samdion1994/mocky-mock/commit/930ce61d20504c4c5e36a06f3744fbc7cf4e4467))
* add BEFORE-EACH/BEFORE-ALL mock scoping to the .cut DSL ([49210ca](https://github.com/samdion1994/mocky-mock/commit/49210ca3d979103814db5e778d232135dfc10497))
* add DEPTMQC example with MQ consumer logic and related copybooks ([50fff6a](https://github.com/samdion1994/mocky-mock/commit/50fff6a5a2f4cb0e15d4aa2b404f799e6d069092))
* add FILE-STATUS IS sugar to the .cut DSL ([347fbf1](https://github.com/samdion1994/mocky-mock/commit/347fbf1ce51f211b6d94865aabe3b574059765d5))
* add terminator reachability primitives + span/line validation ([b35b4ab](https://github.com/samdion1994/mocky-mock/commit/b35b4abee01e19d8ad26920e044caada4efaa83a))
* **analysis,splicer:** support IMS DL/I ENTRY/LINKAGE programs instead of crashing ([7bb9004](https://github.com/samdion1994/mocky-mock/commit/7bb9004f92071135c3fac2c55453470e891b24f0))
* **analysis:** add whole-program safe-section-entry detection ([60b8894](https://github.com/samdion1994/mocky-mock/commit/60b8894994fd87446d7d99a2d8095fd0c1b6c7b3))
* **analysis:** classify STOP RUN/GOBACK as detected terminator sites ([aaee393](https://github.com/samdion1994/mocky-mock/commit/aaee3938ef3664f27b42b1bcbcffac6ae8c49d87))
* **analysis:** classify STOP RUN/GOBACK as detected terminator sites ([5f2c70b](https://github.com/samdion1994/mocky-mock/commit/5f2c70b9c1f3cf3fe88a025a63dcb15906640575))
* **analysis:** classify STOP RUN/GOBACK as detected terminator sites ([dba4da6](https://github.com/samdion1994/mocky-mock/commit/dba4da6ee5e3a19061f78e0b26265e5866ad77b3))
* **analysis:** follow conditionally-nested intermediate PERFORM edges ([ec05b32](https://github.com/samdion1994/mocky-mock/commit/ec05b3264e2cb457961d826e641d8780ce047634))
* **analysis:** recognize safe SECTION-scoped terminators in find_terminator_plans ([c0773a8](https://github.com/samdion1994/mocky-mock/commit/c0773a826fcf815b15c67417f2431e5e989acb60))
* **analysis:** resolve safe section entries in the safe-chain BFS ([3ccccea](https://github.com/samdion1994/mocky-mock/commit/3cccceaded7c6a7d7ad66bdaf6d095eefc13c152))
* **analysis:** safe-chain terminator detection + UNSUPPORTED_TERMINATOR_LAYOUT ([e3aee11](https://github.com/samdion1994/mocky-mock/commit/e3aee114327ef0c914b155aa7f42f0f58b235054))
* auto-scaffold starter .cut files from the mock surface ([9f76605](https://github.com/samdion1994/mocky-mock/commit/9f766054179e61d19ded06e9356ce97e503edc08))
* category-generic DSL (MOCK/VERIFY for file ops, SQL, CICS, DLI, ACCEPT, MQ) + generalized dispatch/driver codegen ([74ea3a8](https://github.com/samdion1994/mocky-mock/commit/74ea3a81fb3e8fe4979fe8334d4e35033c8368ea))
* CLI setup/run drive the Docker toolchain, fail loudly without Docker ([b886551](https://github.com/samdion1994/mocky-mock/commit/b88655169d16a92c49a4dad9f9eb00e9a043f228))
* **cli:** add --keep-sandbox and --verbose for run debugging ([94ef581](https://github.com/samdion1994/mocky-mock/commit/94ef5819f93625b0c4dccd08943b627fcf49689e))
* **cli:** add --trace and --trace-json to run ([b52f199](https://github.com/samdion1994/mocky-mock/commit/b52f1998790db49903ae7531ed6d7d731fa96055))
* **cli:** improve cross-platform reliability and add regnavg example ([4ee0fd5](https://github.com/samdion1994/mocky-mock/commit/4ee0fd5452e6feeb402d880bf3ba4ba103dec76a))
* **cli:** support test cases whose PERFORM target reaches a terminator ([a707572](https://github.com/samdion1994/mocky-mock/commit/a707572326ebd12d85ded1389090af469352f92a))
* **cli:** thread --copybook-path into EXEC SQL INCLUDE resolution for run ([c759c36](https://github.com/samdion1994/mocky-mock/commit/c759c36760c76eb5c916e69872224ced540b2069))
* **cli:** wire the debug subcommand into mockymock, add end-to-end test ([eac848b](https://github.com/samdion1994/mocky-mock/commit/eac848b6f3fb39d3bada41689dd87ab1ae99ac0f))
* comment-and-replace statement span surgery ([4179a0c](https://github.com/samdion1994/mocky-mock/commit/4179a0c4d81677ed17caf826a0b7807fe8d72a79))
* **coverage:** add DEPTIMSM example, proven end-to-end with --coverage ([8627aa9](https://github.com/samdion1994/mocky-mock/commit/8627aa9b55d62b74ba5f7caaf0ed8a6b757b3383))
* **coverage:** compile_source gains a coverage flag ([1a7ff6e](https://github.com/samdion1994/mocky-mock/commit/1a7ff6e315d0784164192cae3f218912fe6d7000))
* **coverage:** parse and format gcov's per-line COBOL coverage output ([dff5c98](https://github.com/samdion1994/mocky-mock/commit/dff5c98b375c662bb1ff5af83991e3d14e401d3d))
* **coverage:** run_gcov executes gcov inside the mockymock-cobc container ([6f4c89f](https://github.com/samdion1994/mocky-mock/commit/6f4c89f01f5ab3488fe4791292b43e0512471073))
* **coverage:** wire --coverage/--coverage-out into mockymock run ([fb7acbc](https://github.com/samdion1994/mocky-mock/commit/fb7acbcef00757a9a72e7b73a67068a2b742041c))
* DATA DIVISION EXEC SQL transform — generated SQLCA, DECLARE stubs, fail-closed INCLUDE ([aaa1ef8](https://github.com/samdion1994/mocky-mock/commit/aaa1ef805ca4b5a999ab5712eddff117d12cecd5))
* **debug:** add bidirectional line mapping for breakpoints ([28c01f2](https://github.com/samdion1994/mocky-mock/commit/28c01f20193e45e64b1bd4537e67738e26e745db))
* **debug:** add DAP adapter on stdio ([01a599e](https://github.com/samdion1994/mocky-mock/commit/01a599ed902024fa728dd564d2f7ac0b45fe31f4))
* **debug:** add GDB/MI session wrapper with coalesced stepping ([13b7344](https://github.com/samdion1994/mocky-mock/commit/13b73440cb683a63c8e0251c8662bb89138e4800))
* **debug:** map COBOL data items to gdb expressions via .c.l.h ([a9ebb91](https://github.com/samdion1994/mocky-mock/commit/a9ebb91d632790acf48f4e14d4ed13e7fe2bdd56))
* **debug:** synthesize the COBOL call stack from GnuCOBOL's frame_stack ([fa917ef](https://github.com/samdion1994/mocky-mock/commit/fa917ef384f7e7394010a062942d96a6d6456b25))
* docker exec-based compile_source ([08fb1c4](https://github.com/samdion1994/mocky-mock/commit/08fb1c41802c52e790ff732311373bcdf82768f0))
* docker exec-based run_binary with container-side timeout ([8af9395](https://github.com/samdion1994/mocky-mock/commit/8af9395af2b690473424ed9d3f020889d6ed30b8))
* Docker toolchain skeleton — image, constants, path mapping ([8bbcd7d](https://github.com/samdion1994/mocky-mock/commit/8bbcd7da7b976793a05619ecd668fb41f7f2bf52))
* driver emits PERFORM ... THRU for range entry points ([3d88412](https://github.com/samdion1994/mocky-mock/commit/3d88412b4891ff0390ad35cbcc6a3053669015a3))
* **dsl:** add MOCK SQL ... ROWS grammar for cursor row sequences ([1bc6fe8](https://github.com/samdion1994/mocky-mock/commit/1bc6fe8d8ca979d132bc413b32e314480e8755e9))
* enhance Windows compatibility and error handling in mockymock ([1e88abd](https://github.com/samdion1994/mocky-mock/commit/1e88abd88f5e28c803abcbb6d62c7c60b2be3349))
* ensure_toolchain() brings up the GnuCOBOL container idempotently ([eea320c](https://github.com/samdion1994/mocky-mock/commit/eea320c9867508a311289309dc29f634cdd2a4fa))
* **examples:** add CICS and dynamic-CALL routing worked examples ([279fb63](https://github.com/samdion1994/mocky-mock/commit/279fb6376db46e2313f273fd9c90dad28b799404))
* **examples:** add CUSTPROG and CLAIMSEG examples and improve discoverability ([6de2d5f](https://github.com/samdion1994/mocky-mock/commit/6de2d5f7f9ccf45c5075d9ac750a8b3214746da1))
* expand USING PROVIDER TESTCASEs into one case per row ([9073baa](https://github.com/samdion1994/mocky-mock/commit/9073baaa814506517c8fda40c728ff46bb4e25c0))
* extract declared FILE STATUS fields from FILE-CONTROL ([6559f97](https://github.com/samdion1994/mocky-mock/commit/6559f97d553edd51819ae13908f0b4a5a90be5ff))
* generate TESTSUITE/TESTCASE driver paragraphs ([fc49a41](https://github.com/samdion1994/mocky-mock/commit/fc49a410564bad78695177a8d4c0855d9a080ccc))
* GnuCOBOL bootstrap and mockymock setup command ([8938b17](https://github.com/samdion1994/mocky-mock/commit/8938b1726f96002739edf286a5381ca79ac62f46))
* Initialize mocky-mock OKF Bundle and add core documentation ([9369ac0](https://github.com/samdion1994/mocky-mock/commit/9369ac016c383d4a7b2bfbb3e2043f2da472fe08))
* inject default-success and FILE-STATUS IS overrides at splice time ([7b54dea](https://github.com/samdion1994/mocky-mock/commit/7b54dea14f2498a12a5695750e0e70a79056ef2a))
* INVUPDT all-boundaries example + integration tests; escape quotes in driver DISPLAYs; docs ([6ab4953](https://github.com/samdion1994/mocky-mock/commit/6ab4953e6a3e6e8bae723e0ce89918de739c8fe7))
* make mockymock installable via uv from anywhere ([de6ad0d](https://github.com/samdion1994/mocky-mock/commit/de6ad0d913bfd3765169c939101fbf3f281a40f0))
* merge per-testcase MOCK CALL bodies into EVALUATE dispatch ([ceb6c1f](https://github.com/samdion1994/mocky-mock/commit/ceb6c1f917a64632465cd2af218efb82a9f55dfe))
* mock dynamic CALLs by the identifier they call through ([34efb56](https://github.com/samdion1994/mocky-mock/commit/34efb56052fe0527daf78b1d41c79c90abd5d1ca))
* mock internal flow targets with MOCK PARAGRAPH / MOCK SECTION ([6233915](https://github.com/samdion1994/mocky-mock/commit/6233915639e7507e0ed54d149e9124f17b527d95))
* mock surface analyzer classifies static/dynamic CALL and detects file/EXEC ([dd77152](https://github.com/samdion1994/mocky-mock/commit/dd771520ceede6a8eb5cc64d807fbad24fbd0b4f))
* mock surface records per-site BoundarySite inventory for every category ([7c482bc](https://github.com/samdion1994/mocky-mock/commit/7c482bc3c822715f4729964a8704901a39e8d55f))
* mutation testing v1 (mockymock mutate) ([56a2006](https://github.com/samdion1994/mocky-mock/commit/56a200619faaf28b91a9dcaee76b6df7d4b4a424))
* ORDRPROC worked example and end-to-end capstone test ([42fb8a0](https://github.com/samdion1994/mocky-mock/commit/42fb8a029fb98122300cfa22211c240b71291806))
* parse __MOCKYMOCK__ stdout output into structured results ([d441e1d](https://github.com/samdion1994/mocky-mock/commit/d441e1d61237255da4da0af670ab76f3d99aa13e))
* parse PROVIDER/HEADER/ROW data-table blocks in .cut files ([9394a55](https://github.com/samdion1994/mocky-mock/commit/9394a552a331c6baeb5dcf594567369e4a05a041))
* per-site splice orchestrator + CLI run pipeline for all categories ([6d99206](https://github.com/samdion1994/mocky-mock/commit/6d99206602ec52226747468fb73c81782c32ad60))
* per-testcase and whole-program refusal gate ([a1d76f4](https://github.com/samdion1994/mocky-mock/commit/a1d76f41b52f16fd6042f30d944baff3c9e3e82b))
* pytest-grade CLI surface -- lint, collect, --case/--tag, JSON report, original-line coverage ([0e4ba33](https://github.com/samdion1994/mocky-mock/commit/0e4ba3353abc754e43368b4ae1708c9a254f990c))
* range-expand PERFORM THRU in reachability; narrow UNSUPPORTED_PERFORM_THRU to degenerate ranges ([8bf42c3](https://github.com/samdion1994/mocky-mock/commit/8bf42c3de954bb32bf9a41155175325b6c8378a3))
* refusal gate matches directives to boundary sites across all categories ([9640a9b](https://github.com/samdion1994/mocky-mock/commit/9640a9b906752701fb5466130d5914efb34e8407))
* refusal gate narrows nested refusals to unspliceable layouts ([b33e91d](https://github.com/samdion1994/mocky-mock/commit/b33e91dd0df16338c6614b1c62e2b27730e627fc))
* **refusal:** refuse on cobolparser dropped-content and lossy-decode warnings ([4da9fa5](https://github.com/samdion1994/mocky-mock/commit/4da9fa5f4349b1d8355a347bc9b7c9dec0772ca3))
* refuse FILE-STATUS IS on a file with no declared status field ([c01f324](https://github.com/samdion1994/mocky-mock/commit/c01f3247a976078ebeb6c5c0e6a19325122fdad6))
* remove local cobc toolchain; all compile/run goes through Docker ([f1aa83c](https://github.com/samdion1994/mocky-mock/commit/f1aa83cf35ed91151eae1262566d54b24be0baee))
* **report:** add trace parser and trace-JSON contract ([2e7459a](https://github.com/samdion1994/mocky-mock/commit/2e7459a7e50be0cd0fd5712579d77236900cd058))
* **report:** parse __MOCKYMOCK__ MOCK markers into TestResult.mock_hits ([8782884](https://github.com/samdion1994/mocky-mock/commit/8782884ddcc51789842716c13bf9bc6a2be537be))
* repository skeleton with cobolparser dependency ([9066c7b](https://github.com/samdion1994/mocky-mock/commit/9066c7b1cec75283b9465b94a7c11930ab1dfe9d))
* **runtime:** compile with -ftraceall and enable COB_SET_TRACE into the sandbox ([24e1b26](https://github.com/samdion1994/mocky-mock/commit/24e1b26199ca6f633fb53d16ed78caea90d537ff))
* **runtime:** compile with -g and start a long-lived gdb MI session ([c703f41](https://github.com/samdion1994/mocky-mock/commit/c703f41280bf8bce1e7a3ca4d3d4df9615b335a1))
* sandbox_dir accepts a root so sandboxes can live under the Docker mount ([a046b7a](https://github.com/samdion1994/mocky-mock/commit/a046b7a13b6404177a39269258e8a17a24f27051))
* scaffold + CLI wire nested-site annotation through generate/run ([e6d006d](https://github.com/samdion1994/mocky-mock/commit/e6d006d856bbc2e59d032f51a19369044f7f1974))
* scaffold generator covers every mockable category, labels MQ, unique SQL prefixes ([f52f990](https://github.com/samdion1994/mocky-mock/commit/f52f9905793ae60817524a972e2400b632733b77))
* scope map + nested-site span annotation in source_map ([a6ff06f](https://github.com/samdion1994/mocky-mock/commit/a6ff06f4b1b9aff473038876c24aaee4028c5f2c))
* SECTION-scoped terminator support (narrow shape) ([ab9e3b4](https://github.com/samdion1994/mocky-mock/commit/ab9e3b49a64b8a9a2a13163380087812bd7903f3))
* splice nested boundary sites at their annotated spans ([9e43755](https://github.com/samdion1994/mocky-mock/commit/9e43755b75a35474918c1d9a411d155c2fb256f7))
* **splicer:** add insert_lines_after primitive ([e017183](https://github.com/samdion1994/mocky-mock/commit/e017183b91c4f5ab9f4303e42f58f7a99347eee5))
* **splicer:** codegen ROWS mocks as a tally-driven EVALUATE block ([fc29cca](https://github.com/samdion1994/mocky-mock/commit/fc29cca0b42b5d4ba46dd8b81d00c1d033404fe6))
* **splicer:** declare and reset UT-EARLY-EXIT per test case ([7b54413](https://github.com/samdion1994/mocky-mock/commit/7b54413c339695cc61751a5119c7b9d04c848c87))
* **splicer:** emit __MOCKYMOCK__ MOCK markers in trace mode ([4bbb2bb](https://github.com/samdion1994/mocky-mock/commit/4bbb2bb8c47fee84f087cc58cd2d10fe29e09a8d))
* **splicer:** emit EXIT SECTION for section-scoped terminator plans ([30e5152](https://github.com/samdion1994/mocky-mock/commit/30e5152625d1776e30659d5ad0ec8e6b1e9a0b7b))
* **splicer:** include actual values in EXPECT/VERIFY failure messages ([b2c52be](https://github.com/samdion1994/mocky-mock/commit/b2c52bec071c3a6ab14eef606e26dc9bd61996b3))
* **splicer:** resolve EXEC SQL INCLUDE host-variable copybooks via --copybook-path ([0499c72](https://github.com/samdion1994/mocky-mock/commit/0499c72e3c33055e7bf046161eb30b9249f1cea0))
* **splicer:** splice terminator neutralization + chain-check insertions ([76c2773](https://github.com/samdion1994/mocky-mock/commit/76c277395c5146ea006109a37d86af03d4f0bfa7))
* **splicer:** terminator neutralization + chain-check codegen ([95fb1a7](https://github.com/samdion1994/mocky-mock/commit/95fb1a739949e5051eab28b4ab07c903ab0ef644))
* statement span detection via sorted boundary markers ([896d983](https://github.com/samdion1994/mocky-mock/commit/896d983cfc69b38b5cc8356954c91018feecf0f9))
* track nested_in_boundary ancestry + annotation fields on BoundarySite ([62a48c0](https://github.com/samdion1994/mocky-mock/commit/62a48c0f605edff9f002eb3fc776017375141be9))
* walking skeleton proves compile+run loop against real cobc ([79d7853](https://github.com/samdion1994/mocky-mock/commit/79d7853f4239833628785a75a9fba0a6ebf0c712))
* wire copybook expansion into generate and run ([3e9f6f1](https://github.com/samdion1994/mocky-mock/commit/3e9f6f1165f1740bbdef55e0e76061f7900ec9bc))
* wire generate and run subcommands end to end ([dc21e0b](https://github.com/samdion1994/mocky-mock/commit/dc21e0bcfbc5a7cd0300e36ec680793257eb5678))
* working-storage reset generation for test-case isolation ([35bf83a](https://github.com/samdion1994/mocky-mock/commit/35bf83abab42eb3bfc4c8a780e4c3ea6e28e4936))


### Bug Fixes

* address whole-branch review findings for BEFORE blocks + FILE-STATUS ([4e0185a](https://github.com/samdion1994/mocky-mock/commit/4e0185aaf8418786e8f716383ec73c06a3152d0a))
* **analysis:** address Task 3 review nits in find_terminator_plans ([8b8378d](https://github.com/samdion1994/mocky-mock/commit/8b8378df9d8d8b042a5865eab9073d40bcbee674))
* **analysis:** refuse terminators reached only via a looping PERFORM ([524a72e](https://github.com/samdion1994/mocky-mock/commit/524a72e7b508878b48e31566e161e4202aaf5a3e))
* **analysis:** refuse terminators reached via GO TO fall-through ([57526fc](https://github.com/samdion1994/mocky-mock/commit/57526fcefd87e1b4415855b6304ab5a1d44126ec))
* **analysis:** refuse terminators reached via GO TO fall-through ([8fa96ec](https://github.com/samdion1994/mocky-mock/commit/8fa96ec77b797da03f4870dd9bc9e9c8598f5bc7))
* bound compile_source docker exec with a host-side timeout ([f677a4a](https://github.com/samdion1994/mocky-mock/commit/f677a4aaf8a3d3e4a6aeb6963b10c367018b1bf9))
* bundle Dockerfile inside the package so `uv tool install` works ([34caac6](https://github.com/samdion1994/mocky-mock/commit/34caac63c09139e26af7bb222fbf46c3772d0e6a))
* catch subprocess.TimeoutExpired/FileNotFoundError in run_binary ([c82ffe7](https://github.com/samdion1994/mocky-mock/commit/c82ffe7265574d2b5c9e3e4b5340434a9b3a3784))
* **cli:** print individual parse errors in run; correct refusal docstring ([48992b1](https://github.com/samdion1994/mocky-mock/commit/48992b111d8bdcc74a756ccfa374fed13a749356))
* **cli:** retain sandbox for --verbose so the printed path is actionable ([f862c89](https://github.com/samdion1994/mocky-mock/commit/f862c89b2a750fca9bd8da4da7de93819652af26))
* **cli:** strip PROCESS/CBL precompiler directives before compiling ([aebc242](https://github.com/samdion1994/mocky-mock/commit/aebc242b135eeabff7f8ca6ef3846e2885a7e34a))
* close silent-gap findings in report layer, DSL, and CLI report writes ([988c814](https://github.com/samdion1994/mocky-mock/commit/988c814a59ada5a088e619f4d87baa6c263b3fc9))
* correct PROVIDER grammar diagram order in dsl.md (after TESTSUITE, not before) ([04a215c](https://github.com/samdion1994/mocky-mock/commit/04a215c71a90034d9c36fd3574194c1f6da07c70))
* **coverage:** compile_source pins the container working directory ([dee5934](https://github.com/samdion1994/mocky-mock/commit/dee59346d2e0ebd5a0609dee0101366502f355f6))
* **debug:** harden MI parser, honor setBreakpoints replace, guard dispatch ([2428c36](https://github.com/samdion1994/mocky-mock/commit/2428c36a998c2380464a9cc266ddcc9ca47b5706))
* **debug:** implement evaluate handler and improve step coalescing ([60f62c6](https://github.com/samdion1994/mocky-mock/commit/60f62c637ffa8df7abe830b377e3e9d0dab32154))
* **deps:** bump cobolparser pin to b130ec8; adapt UNRESOLVED_COPYBOOK to structured COPY warning ([ca39671](https://github.com/samdion1994/mocky-mock/commit/ca39671799acd866af754e14718be4e479953e3e))
* **deps:** bump cobolparser pin to b3e81ed (PR [#89](https://github.com/samdion1994/mocky-mock/issues/89) review fixes) ([cca9991](https://github.com/samdion1994/mocky-mock/commit/cca999126a8a458a041c96d63e4b4f86f0890af4))
* **deps:** bump cobolparser pin to c9a9499, fix statement_span blank-line trim ([d8fd9cb](https://github.com/samdion1994/mocky-mock/commit/d8fd9cbe8812e9342f768b40fe608d71b1b2a894))
* **deps:** bump cobolparser pin to c9a9499, fix statement_span blank-line trim ([19e388f](https://github.com/samdion1994/mocky-mock/commit/19e388fa1a79b1286dd83c6926034d4e9125f2ee))
* **deps:** bump cobolparser pin to d2bc7c2, fixes NIST IC101A/IC116M ([1086ba1](https://github.com/samdion1994/mocky-mock/commit/1086ba1283addc9e4e43cde695f5445b1bcedfc7))
* drop deprecated license classifier that breaks pip install ([61959e7](https://github.com/samdion1994/mocky-mock/commit/61959e7eeda7c5d2bc2a0818626a8ce76773f54d))
* **dsl:** raise on unterminated MOCK body instead of swallowing file ([6eb371b](https://github.com/samdion1994/mocky-mock/commit/6eb371b5e81cff39f2125c4e4117f4ae2c214195))
* **dsl:** reject duplicate PERFORM in a single TESTCASE ([4385223](https://github.com/samdion1994/mocky-mock/commit/4385223d298ac7c9badb07edda6df3a3f6f22880))
* **dsl:** support subscripted table names in EXPECT/MOVE directives ([aecf9a2](https://github.com/samdion1994/mocky-mock/commit/aecf9a2a7dad8d6e49e609929b903e7562105828))
* **examples:** ACCTPRG.cut mock READ set a field the splice removes ([31ef2c6](https://github.com/samdion1994/mocky-mock/commit/31ef2c604cbf17b7d5bd0d6094032440d94d8f8b))
* guard publish-public.yml's tag resolution against bad/missing manifest data ([b371c2f](https://github.com/samdion1994/mocky-mock/commit/b371c2f400e7cd383ab9ac624adf0490764e2f01))
* JUnit XML failures attribute counts failed cases, not failed checks ([26a0fe5](https://github.com/samdion1994/mocky-mock/commit/26a0fe586f432b4a32cd4cc61f4940e76918171e))
* main was broken (unresolved merge markers) + all 24 examples now pass ([cc05ee3](https://github.com/samdion1994/mocky-mock/commit/cc05ee354ab672a105d0f49d11773802ad4e1cba))
* **plan:** Task 1 must also exclude terminator labels from check_test_case's SORT/MERGE catch-all ([374998e](https://github.com/samdion1994/mocky-mock/commit/374998e48ae2e2fda9a519981a5e1ea19a98a32b))
* **plan:** Task 1 review found two more consequences of the new labels ([ac8e1df](https://github.com/samdion1994/mocky-mock/commit/ac8e1dfbc8051e7f49f0efc0505b5d6948092f28))
* **plan:** wire up terminator-own-span and chain-line-ownership checks ([3f95682](https://github.com/samdion1994/mocky-mock/commit/3f9568244f778c075ffac2b384acfd655f89aed2))
* recurse into nested statement bodies and refuse PERFORM THRU in reachability BFS ([23d2697](https://github.com/samdion1994/mocky-mock/commit/23d2697dde50cc1c6f3ef0565a1ab3939f0db9a9))
* recurse into nested statement bodies in mock surface analysis ([5144ba2](https://github.com/samdion1994/mocky-mock/commit/5144ba25cb8790a6591b85b0db3cfa859ff78c98))
* refuse empty PROVIDER row values; document mock-directive aliasing ([9d5bf87](https://github.com/samdion1994/mocky-mock/commit/9d5bf8709c1fdc46c00c27b6fb3740f7facf5cd1))
* refuse malformed FILE-STATUS lines instead of splicing them verbatim ([4aeec1d](https://github.com/samdion1994/mocky-mock/commit/4aeec1de6b3ec69f9987a265d522b3163d79c6cf))
* refuse MOCK CALL targeting a nested (unsplicable) call site ([ef66795](https://github.com/samdion1994/mocky-mock/commit/ef667957349f4ffc5c49dc4fe7499f65123abfd3))
* refuse stray statements inside an open PROVIDER block ([9880583](https://github.com/samdion1994/mocky-mock/commit/98805833382cecf2d8e6345ffa10aa19f66fd052))
* refuse unmocked reachable static CALL sites (UNMOCKED_CALL) ([5ed3ac0](https://github.com/samdion1994/mocky-mock/commit/5ed3ac095b2b53c76cc3ae9032fa7294c47a19cb))
* refuse unresolved COPY statements (UNRESOLVED_COPYBOOK) ([6cd994f](https://github.com/samdion1994/mocky-mock/commit/6cd994fd72f708d69a6a8081dea55bc8c8da8da0))
* reject BEFORE-ALL/BEFORE-EACH opening while a prior before-block is unterminated ([beb963f](https://github.com/samdion1994/mocky-mock/commit/beb963f6adf441a75d6979c3ca15a71e2eaee907))
* rename duplicate-case-start "first name" to "previous name" ([669a871](https://github.com/samdion1994/mocky-mock/commit/669a871e6278781af69f87c9a21b98a7465f906f))
* **report:** count orphan testcases in JUnit tests= attribute ([531f63e](https://github.com/samdion1994/mocky-mock/commit/531f63e4cf5eb78749de874a328b2ada811f365e))
* **report:** surface FAIL lines with unknown case id instead of dropping them ([75ec041](https://github.com/samdion1994/mocky-mock/commit/75ec0413139fb67b1ee3333f0018cfca898b164d))
* **reset:** never target FILLER items when restoring group child VALUEs ([5d60c8f](https://github.com/samdion1994/mocky-mock/commit/5d60c8ffdda74f14cad8fc6bf566e85dea0f4fec))
* **reset:** restore group children's VALUE clauses after INITIALIZE ([cdd909d](https://github.com/samdion1994/mocky-mock/commit/cdd909d232339e27c592d9974e7ddda36d31d585))
* resolve unresolved merge-conflict markers left on main ([bd60da9](https://github.com/samdion1994/mocky-mock/commit/bd60da966cf52e42e7288af1578ff402050814bb))
* **runtime:** content-tag the GnuCOBOL image so Dockerfile edits rebuild ([b84609a](https://github.com/samdion1994/mocky-mock/commit/b84609aa641606caf266adea2ab9e25fcf3811db))
* **runtime:** harden the GnuCOBOL container that runs untrusted COBOL ([6b16dc6](https://github.com/samdion1994/mocky-mock/commit/6b16dc6d5fc2149cf734043d5e96a0ac850ae55d))
* **runtime:** keep DAC_OVERRIDE so container-root can read the bind mount ([ab719da](https://github.com/samdion1994/mocky-mock/commit/ab719da9391d8d242fdf17eea93bdfd2b99343b8))
* **splicer:** satisfy mypy and black on Task 6's terminator-splice changes ([77b7062](https://github.com/samdion1994/mocky-mock/commit/77b7062c6a353b6f492c27328835ab200bb9c59b))
* **splicer:** terminate chain-check insertion when the PERFORM it follows ends its own sentence ([d6d7913](https://github.com/samdion1994/mocky-mock/commit/d6d7913322b5f0bc71c706eb0b55a40eb4cf4a2f))
* strengthen STATELKUP collect test, correct README line numbers ([f1a3ddc](https://github.com/samdion1994/mocky-mock/commit/f1a3ddc741d929af2ba14584e2c0fece627ed132))
* **test:** give the debug spike a visible statement to step onto ([2c65d95](https://github.com/samdion1994/mocky-mock/commit/2c65d9590942014825d9096adcd0ef77652a5b3e))
* **tests:** rewrite stale out-of-line PERFORM VARYING integration pin ([b7bc45b](https://github.com/samdion1994/mocky-mock/commit/b7bc45bdf0c59ffb31afba124ebafcfc86001f7c))
* **tests:** rewrite stale out-of-line PERFORM VARYING pinning tests ([f959e5e](https://github.com/samdion1994/mocky-mock/commit/f959e5e2390f8afab9fb4f4089f69005b560cbef))


### Documentation

* add 2026-07-07 full-repo audit report ([e53e318](https://github.com/samdion1994/mocky-mock/commit/e53e318625b4f73de901621d339307d7b1ca438d))
* add CLI implementation plan for execution-trace debug support ([f9db252](https://github.com/samdion1994/mocky-mock/commit/f9db25269210c4d06e08e5466dcc5090e3541023))
* add coverage-reporting design (v1 scope) ([3598bda](https://github.com/samdion1994/mocky-mock/commit/3598bda32c5fd7b302bfa474c3e8557cc7a056b5))
* add design and plan for the cobol-mocky-mock publish pipeline ([f7218d3](https://github.com/samdion1994/mocky-mock/commit/f7218d33c9b614a5fd8f988db2bd8beb0e3eac26))
* add implementation plan for BEFORE-EACH/BEFORE-ALL and FILE-STATUS ([97f893f](https://github.com/samdion1994/mocky-mock/commit/97f893fdaae8b3da8ade3cd75242ebad2835a5f0))
* add implementation plan for coverage reporting ([3dc7719](https://github.com/samdion1994/mocky-mock/commit/3dc7719d77779f0e07f2955ca4e2c825cb5b91b7))
* add implementation plan for GOBACK/STOP RUN terminator support ([ab40693](https://github.com/samdion1994/mocky-mock/commit/ab406930961351c317ff4814a58dbcca75f8adbf))
* add implementation plan for narrow SECTION-scoped terminator support ([6d53ea9](https://github.com/samdion1994/mocky-mock/commit/6d53ea920b6b3be368758fd8fe54ebc5f375355b))
* add implementation plan for SQL v1 (EXEC SQL INCLUDE + cursor ROWS) ([fae822f](https://github.com/samdion1994/mocky-mock/commit/fae822f223d72a4eb586cc68ca3693300211f9c7))
* add integration-testing direction design notes ([0a7da52](https://github.com/samdion1994/mocky-mock/commit/0a7da52cfa8bf38bade1b9934f4406c8270ee60d))
* add mockymock lint command design ([083afa2](https://github.com/samdion1994/mocky-mock/commit/083afa2c1b3445dc2801a28f359145f7413317ac))
* add MVP design spec for mockymock ([a3081e9](https://github.com/samdion1994/mocky-mock/commit/a3081e967f482c590ff229c16fc06d4d7bf5f24a))
* add MVP implementation plan for mockymock ([d72192c](https://github.com/samdion1994/mocky-mock/commit/d72192cd5968393a54eda1ae31794ba191b09323))
* add PROVIDER parameterized test cases implementation plan ([a662974](https://github.com/samdion1994/mocky-mock/commit/a6629748651d40980f97887841445388f383a549))
* add real-world readiness audit for mockymock with findings and recommendations ([340e355](https://github.com/samdion1994/mocky-mock/commit/340e355cc540621b101dd4c6e08f0eb7f12ebb71))
* add Task 16 (copybook expansion wiring) to the plan ([f914314](https://github.com/samdion1994/mocky-mock/commit/f914314d986e20132096d68e4b8391d0072e0cc3))
* add TAXFILE example and document BEFORE-EACH/FILE-STATUS features ([252134c](https://github.com/samdion1994/mocky-mock/commit/252134cbbd14ea0be435c4793664c42f252a5449))
* addendum -- per-site mock dispatch is a second uncovered-line source ([5f7e6fe](https://github.com/samdion1994/mocky-mock/commit/5f7e6fe56aa1e4d04f714694198b7ee78a6cb06e))
* clarify relationship with cobol-check in README ([1bf7e2d](https://github.com/samdion1994/mocky-mock/commit/1bf7e2d62546e1d0c4b28a0153ce112c330c55c3))
* clarify SECTION-scoped terminator exclusion in find_terminator_plans docstring ([9ebdb5a](https://github.com/samdion1994/mocky-mock/commit/9ebdb5a9d6c3bee4b502a1e32a5849b9b59efeaa))
* correct call-stack synthesis mechanism per real implementation ([cb83b95](https://github.com/samdion1994/mocky-mock/commit/cb83b959bc2f64da4a64a7ca83ba118187d1f04a))
* correct post-extraction build-job description ([735873c](https://github.com/samdion1994/mocky-mock/commit/735873c3ebd9a57f413aa78ed585d12059b5d2dd))
* correct run_gcov mechanism -- docker exec -w works fine via subprocess ([a0c90ed](https://github.com/samdion1994/mocky-mock/commit/a0c90ed8d700435267770320c3c3f43d4ace3631))
* correct Task 14 nested-CALL fix design after BLOCKED discovery ([37b0eba](https://github.com/samdion1994/mocky-mock/commit/37b0ebab52e4e3a1b22c1bcb77b55c3ea4783ddc))
* **coverage:** README + OKF concept for coverage reporting ([878bd62](https://github.com/samdion1994/mocky-mock/commit/878bd62caf99801f6a298b19cee7447f92a35227))
* design + plan for nested mock targets ([c17b550](https://github.com/samdion1994/mocky-mock/commit/c17b550eebfa62866694b89889c795d27c61cb3a))
* design BEFORE-EACH/BEFORE-ALL scoping and FILE-STATUS sugar ([3ae0b45](https://github.com/samdion1994/mocky-mock/commit/3ae0b45ee43a9746a537aaf177a8035f7feaadc1))
* design conditionally-nested intermediate PERFORM support ([3e8a118](https://github.com/samdion1994/mocky-mock/commit/3e8a118e509c6d04dfd07923f5da7af4f4247612))
* design EXEC SQL INCLUDE host-var copybook expansion + cursor ROWS sugar ([7a8cb6a](https://github.com/samdion1994/mocky-mock/commit/7a8cb6a6082da9588b9c57f4897472c95996a776))
* design execution-trace debug support for CLI + VS Code extension ([c9db7b3](https://github.com/samdion1994/mocky-mock/commit/c9db7b375cf565addfc0eafdcc9c3b691c1177ef))
* design for GOBACK/STOP RUN terminator support ([ed7f402](https://github.com/samdion1994/mocky-mock/commit/ed7f4025f0acddc9439f57bec487c8448fda3bd9))
* design for IMS DL/I ENTRY/LINKAGE support (neutralize-and-promote) ([7a80593](https://github.com/samdion1994/mocky-mock/commit/7a805934145ba1315d5049b26148d2e5189f4f40))
* design for real-world COBOL e2e examples sourced from legacy-application ([5600e18](https://github.com/samdion1994/mocky-mock/commit/5600e1817f44df4d493bb4ca68e1af5fb5cdf7d3))
* design GO TO fall-through terminator hazard guard ([aa6956d](https://github.com/samdion1994/mocky-mock/commit/aa6956d2629cd79c01ab58996cfb89ce28446b36))
* design GO TO-reachable terminator investigation ([2b74c1d](https://github.com/samdion1994/mocky-mock/commit/2b74c1df2c182df96820fd8073d7451d2950f4ec))
* design narrow SECTION-scoped terminator support (shape 1 only) ([9e8b5ac](https://github.com/samdion1994/mocky-mock/commit/9e8b5ac1b632c8f75264a015fbb0ae569293c325))
* design PROVIDER parameterized test cases ([d6f6169](https://github.com/samdion1994/mocky-mock/commit/d6f616989dd1995f9ef0592b8ab0f3633623fb61))
* Docker GnuCOBOL toolchain design spec ([a290cb5](https://github.com/samdion1994/mocky-mock/commit/a290cb528b995ba68621dcf2417ecae9e20d41b9))
* Docker toolchain implementation plan ([f97f4a0](https://github.com/samdion1994/mocky-mock/commit/f97f4a0e813c2e7d0bf22ce54dca9ce92d53a424))
* document --trace in README and OKF bundle ([acd0120](https://github.com/samdion1994/mocky-mock/commit/acd0120645cda4c1329f82f820d80477c3c1ddb9))
* document call-site splicer nested-statement fix (Task 14 Important finding) ([cede0b4](https://github.com/samdion1994/mocky-mock/commit/cede0b430b010c56d89ee9138a40fd648befcc21))
* document EXEC SQL INCLUDE resolution and ROWS cursor sugar ([c76097a](https://github.com/samdion1994/mocky-mock/commit/c76097a31a835799c6ef3bd29e494005e3c78444))
* document EXEC SQL INCLUDE resolution and ROWS cursor sugar ([dcfadc9](https://github.com/samdion1994/mocky-mock/commit/dcfadc9af3eb542912c82072c7da8f75fcd32048))
* document mockymock debug in OKF bundle and README ([37a56b3](https://github.com/samdion1994/mocky-mock/commit/37a56b3957d001ae776f33efd6908925b70c67b5))
* document PROVIDER parameterized test cases ([43e0952](https://github.com/samdion1994/mocky-mock/commit/43e095247a656589cb5bda3b868d7b3d8faa4ec2))
* document recursive nested-statement detection requirement (Task 5) ([132ce87](https://github.com/samdion1994/mocky-mock/commit/132ce871937d48111a7fb8dc89158ea11b049b31))
* document refusal-gate reachability BFS fix (Task 6 Critical finding) ([50facc3](https://github.com/samdion1994/mocky-mock/commit/50facc3cba6d1cb08451542aea69486041f61a07))
* document the public binary publish pipeline ([491b46b](https://github.com/samdion1994/mocky-mock/commit/491b46b4c0b40c24903f623ec9268a8af4f221e2))
* fix .okf/log.md entry ordering to newest-first ([34e9731](https://github.com/samdion1994/mocky-mock/commit/34e97319f3d55f1f1788f22d8daaaa56ef1449b6))
* fix documentation inconsistencies flagged in PR review ([1057335](https://github.com/samdion1994/mocky-mock/commit/105733546fff103c845b6a7e44645d998614547a))
* fix PROVIDER HEADER/ROW quoting convention ([e224f7a](https://github.com/samdion1994/mocky-mock/commit/e224f7abd1dde04ed05ab8d8fe9bcd264bd37137))
* GO TO-reachable terminators investigation (no fix found, refusal confirmed permanent) ([3ab8c0d](https://github.com/samdion1994/mocky-mock/commit/3ab8c0db5e00f418b3671f73057bcb14fedfbd8d))
* implementation plan for conditionally-nested intermediate PERFORM ([53690d6](https://github.com/samdion1994/mocky-mock/commit/53690d67b31b7cc8728836b79592f21daae3136e))
* implementation plan for GO TO fall-through terminator hazard guard ([cd617a1](https://github.com/samdion1994/mocky-mock/commit/cd617a126f3caf2b1e90cb9e79ecfc25f12b1c1f))
* implementation plan for GO TO-reachable terminator investigation ([0ec47b5](https://github.com/samdion1994/mocky-mock/commit/0ec47b5d5102b651f70af8cf846b893387468aa0))
* implementation plan for real-world DEPTMQP/DEPTMQC e2e examples ([3ede03b](https://github.com/samdion1994/mocky-mock/commit/3ede03bc592c3860289e17b580d00f38372606a4))
* link publishing.md's See Also citations ([f2e7852](https://github.com/samdion1994/mocky-mock/commit/f2e7852f39ac6e25afd6fc0ccd5e362ca15f23b2))
* mark coverage-reporting design doc as implemented/superseded ([a86490a](https://github.com/samdion1994/mocky-mock/commit/a86490a2d70d9b8172ef66bb20987d9b3bc1685b))
* mock-all-boundaries v2 design — FILE/SQL/CICS/DLI/ACCEPT/MQ mock categories ([56f35a6](https://github.com/samdion1994/mocky-mock/commit/56f35a62cfafae03f66fee0364ca995cfd2432fb))
* note INCLUDE-resolved host vars aren't reset between test cases ([303db3c](https://github.com/samdion1994/mocky-mock/commit/303db3c53d3fd46a87736f597fe46a734a05119d))
* PERFORM THRU implementation plan; design facts corrected (phantom paragraphs are empty artifacts) ([c72cc0f](https://github.com/samdion1994/mocky-mock/commit/c72cc0fa6f84e3e992239993ec5b090d140f076d))
* PERFORM THRU support design (range-expanded reachability + .cut driver THRU) ([f636ab3](https://github.com/samdion1994/mocky-mock/commit/f636ab3a8b6b648062eb28a5ccb6bba23660ef61))
* point README at the new .okf/ knowledge bundle ([ec0ee88](https://github.com/samdion1994/mocky-mock/commit/ec0ee8866842709a5f24c240063696b3cc36bc05))
* polish GO TO investigation writeup per final review ([2900520](https://github.com/samdion1994/mocky-mock/commit/290052018024c131d95830839eeb5bd8a8e2fd80))
* README reflects nested-mock-target support and narrowed refusals ([fd12393](https://github.com/samdion1994/mocky-mock/commit/fd123939b485c432c17a2178ebf1fb1e472a823d))
* real-world readiness implementation plan ([db37b3a](https://github.com/samdion1994/mocky-mock/commit/db37b3a035f5523ee53962910b1cdda18720f4c8))
* reconcile hardening descriptions with the retained DAC_OVERRIDE cap ([16c6551](https://github.com/samdion1994/mocky-mock/commit/16c6551d03306fc69ce51bf8cd3f4dda7e0ebad5))
* reconcile plan's pytest-cov contradiction (Task 1 review finding) ([6f4ebfc](https://github.com/samdion1994/mocky-mock/commit/6f4ebfc74e8fd72c423d70c9d8b625a0ca77ff47))
* record GO TO-reachable terminator investigation outcome ([fd918e9](https://github.com/samdion1994/mocky-mock/commit/fd918e9293f56c3b25fc8fea036462f8769de65f))
* refine INCLUDE resolution to route through public expand_copybooks ([716c116](https://github.com/samdion1994/mocky-mock/commit/716c11650d6e02695ac78976e45f660b2092c61f))
* refine wiring to precompute nested insertion points in refusal.py ([2349ca0](https://github.com/samdion1994/mocky-mock/commit/2349ca0726293cdfaba15ed31365a6a562805915))
* refresh timestamps on analysis.md/splicer.md for SECTION-scoped update ([b76a533](https://github.com/samdion1994/mocky-mock/commit/b76a53389b3039b94f11968ff2d99a7446df1aaf))
* remove obsolete local-GnuCOBOL Windows notes from README ([c177808](https://github.com/samdion1994/mocky-mock/commit/c177808342a981a2f47bf323522585067acb1c6f))
* revise GOBACK/STOP RUN design to Approach B (EXIT PARAGRAPH propagation) ([b018ff2](https://github.com/samdion1994/mocky-mock/commit/b018ff2c5cf2873aca07f013ace37f3da30ab095))
* revise real-world COBOL examples design after spiking all candidates ([3eeecfb](https://github.com/samdion1994/mocky-mock/commit/3eeecfb1e98301c89bbe4d76ad00620ca229adc7))
* rewrite implementation plan for Approach B (EXIT PARAGRAPH propagation) ([e762c7c](https://github.com/samdion1994/mocky-mock/commit/e762c7c5dc0eb6d8b68dc68f8075f8bb239f3c62))
* sync GOBACK/STOP RUN terminator support (Approach B) ([64c3e65](https://github.com/samdion1994/mocky-mock/commit/64c3e65a223e572c969d49fd0eee4d0f03126ddc))
* sync README DSL reference and OKF concepts with BEFORE/FILE-STATUS/PROVIDER wave ([e783c37](https://github.com/samdion1994/mocky-mock/commit/e783c3780b9a38cedede8c912a112e3031c50496))
* sync SECTION-scoped terminator support (narrow shape) ([7a68afb](https://github.com/samdion1994/mocky-mock/commit/7a68afb6bac4af5a2fa37f286ec5730d71af3bc2))
* **test:** note that the unneutralized-shape crash is UB, not guaranteed ([8356f16](https://github.com/samdion1994/mocky-mock/commit/8356f164f199f962dd81971758eb96991d17836a))
* update testing documentation and logs ([9038462](https://github.com/samdion1994/mocky-mock/commit/903846223d7abe4c7e8868a49dde3e3d36f2338a))
