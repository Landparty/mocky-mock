# Changelog

## [0.14.0](https://github.com/Landparty/mocky-mock/compare/v0.13.0...v0.14.0) (2026-11-02)


### Features

* **runner:** log every step of a job and post the job's timeline ([4a9fa71](https://github.com/Landparty/mocky-mock/commit/4a9fa715cae117ebf2d753723bbc0099173fbedc))
* **runner:** log every step of a job and post the job's timeline ([6297217](https://github.com/Landparty/mocky-mock/commit/62972178ac96c496e20e30f598eb02772b38bdf9))


### Bug Fixes

* alternate-key READ counts and CICS keys/resources in baselines ([#402](https://github.com/Landparty/mocky-mock/issues/402), [#400](https://github.com/Landparty/mocky-mock/issues/400)) ([#405](https://github.com/Landparty/mocky-mock/issues/405)) ([7f1984a](https://github.com/Landparty/mocky-mock/commit/7f1984a297b3a9397806237bced65f33f0f912f0))
* **generate:** mock OPEN per mode, fail the right file of a multi-file OPEN, record shared captures bare ([753fffd](https://github.com/Landparty/mocky-mock/commit/753fffdbb443a73bd076ae7acc8b13b3f4df6b5a))
* **generate:** mock OPEN per mode, fail the right file of a multi-file OPEN, record shared captures bare ([d3ff8aa](https://github.com/Landparty/mocky-mock/commit/d3ff8aac50800bd168fbefa0c284897ecf2bb501))
* stress-test findings (fixed clock, merged case branches, DL/I rows, MQ codes, DFHAID, orphaned compilers) ([b8304bb](https://github.com/Landparty/mocky-mock/commit/b8304bb1959dc00d2671ea673122522cd4a1aab3))
* stress-test findings: fixed test clock, merged case branches, DL/I rows per call, pinned MQ codes, DFHAID, no orphaned compilers ([d688651](https://github.com/Landparty/mocky-mock/commit/d688651434435c169a784047d12bbfb5b0d9178c))

## [0.13.0](https://github.com/Landparty/mocky-mock/compare/v0.12.0...v0.13.0) (2026-11-02)


### Features

* **baseline:** record cursor inputs and what a program returns (baseline v2); oraclemix example ([20b4df8](https://github.com/Landparty/mocky-mock/commit/20b4df826e9f5b47f9c1de6720402cac2238fc2c))
* behaviour baselines (run --record-baseline / --baseline) and mockymock runner ([#396](https://github.com/Landparty/mocky-mock/issues/396)) ([01b1476](https://github.com/Landparty/mocky-mock/commit/01b14768835d1de4cc163d3e6c8706d767eb2191))
* **dsl:** USE REAL CALL links real subprograms into a suite (load-module tests) ([#392](https://github.com/Landparty/mocky-mock/issues/392)) ([a56090d](https://github.com/Landparty/mocky-mock/commit/a56090da4733e859253046a6e4375c6c780ea589))
* **examples:** ordmod load module; MQ placeholders answer CompCode ([#393](https://github.com/Landparty/mocky-mock/issues/393)) ([31ba3df](https://github.com/Landparty/mocky-mock/commit/31ba3df43474f14d2da4ec14ed3b2ebc49cce645))
* **generate:** CICS entry parameters from the bundle, hex literals, found-record cases in real subprograms ([b7ea7cb](https://github.com/Landparty/mocky-mock/commit/b7ea7cb05094155f5a2a303aacf5b6f598007414))
* **oracle:** baseline v2, real dynamic CALL targets, runner --scenarios; oraclemix example ([c7e1c59](https://github.com/Landparty/mocky-mock/commit/c7e1c59e69e007b8d6f320fb1161487e0f8b98e5))
* **real-call:** a dynamic CALL runs a USE REAL CALL program; runner allows --scenarios ([faa958b](https://github.com/Landparty/mocky-mock/commit/faa958b80a19e28c7c0d5e1c96b55b3ee2a0052b))
* VSAM READ access forms, FILE STATUS cases, VSAM samples ([8c9df40](https://github.com/Landparty/mocky-mock/commit/8c9df40a3b19567d3e4f433cd2fa7dc9554eb46b))
* VSAM READ access forms, FILE STATUS cases, VSAM samples ([2e1fef6](https://github.com/Landparty/mocky-mock/commit/2e1fef6e1c7329c3a4269d2b30efba7220a2fa2e))


### Bug Fixes

* **dsl:** a quoted PROVIDER placeholder takes the row value's content ([81c4541](https://github.com/Landparty/mocky-mock/commit/81c454170d76a81ab8bff8fab69f4e40e3790ad4)), closes [#376](https://github.com/Landparty/mocky-mock/issues/376)
* **dsl:** give the in-literal placeholder substitution a typed function ([c530fb6](https://github.com/Landparty/mocky-mock/commit/c530fb686cc3de91bd7f3000056162c47668426a)), closes [#376](https://github.com/Landparty/mocky-mock/issues/376)
* **generate:** IMS MPP scaffolds end their GU loop on QC ([#394](https://github.com/Landparty/mocky-mock/issues/394)) ([192245f](https://github.com/Landparty/mocky-mock/commit/192245f6d62cd57e2c0c3225c3db2b1860ddb731))
* open-issue sweep ([#374](https://github.com/Landparty/mocky-mock/issues/374), [#375](https://github.com/Landparty/mocky-mock/issues/375), [#376](https://github.com/Landparty/mocky-mock/issues/376), [#384](https://github.com/Landparty/mocky-mock/issues/384)) ([3326b5f](https://github.com/Landparty/mocky-mock/commit/3326b5f9bf73425f53a7e720640ae3f818a74424))
* **record:** skip a CAPTURE golden for a CALL that never ran ([3852224](https://github.com/Landparty/mocky-mock/commit/3852224ed03c2b552fa8356e5afd09207defbe6e)), closes [#384](https://github.com/Landparty/mocky-mock/issues/384)
* **report:** escape terminal control characters in the console listing ([fe94b63](https://github.com/Landparty/mocky-mock/commit/fe94b637cac1814d5da2443af40c4b6370108c79)), closes [#375](https://github.com/Landparty/mocky-mock/issues/375)
* **report:** show a failing numeric EXPECT's value, not its DISPLAY image ([8d8ff80](https://github.com/Landparty/mocky-mock/commit/8d8ff8012ae97ed1325e88a84a330795a1c999f1)), closes [#374](https://github.com/Landparty/mocky-mock/issues/374)
* second field run (PREMCALC, RECFMT, LEDGRPT, DATECHK) ([#358](https://github.com/Landparty/mocky-mock/issues/358)) ([989b2a7](https://github.com/Landparty/mocky-mock/commit/989b2a7c4b3bcba65d8b35aeb84bd6ef7d97c9ba))
* **skills:** resync the shipped cobol-analysis skill with cobol-parser ([4e65822](https://github.com/Landparty/mocky-mock/commit/4e65822c709b3237fa5ec515d79589d7567e573a))
* test an unnamed main line, doctor fails on a broken config, journal and skills-mode fixes ([#395](https://github.com/Landparty/mocky-mock/issues/395)) ([9dbe216](https://github.com/Landparty/mocky-mock/commit/9dbe2160ba59d70df0925b3cde24a3348c038cd9))


### Documentation

* **oraclemix:** results after the branch-reach fixes ([0472567](https://github.com/Landparty/mocky-mock/commit/04725673b4b1312f3fe2f465d12b46404e674b22))

## [0.12.0](https://github.com/Landparty/mocky-mock/compare/v0.11.0...v0.12.0) (2026-10-29)


### Features

* **copybooks:** find exports named gttlbi0a.copy and other near-misses ([cf600d1](https://github.com/Landparty/mocky-mock/commit/cf600d1a2d75ca1ba87a55fb4ac47d36b7938fa5))
* **copybooks:** stage exports the search cannot match under their member name ([3c4aae5](https://github.com/Landparty/mocky-mock/commit/3c4aae57fba0bd2a6672d8a739d2b9869363c8f3))
* **generate:** fill CALL arguments the layout index misses; branch dynamic CALL mocks per target ([03d863c](https://github.com/Landparty/mocky-mock/commit/03d863cd1a6888fed950e628da786d679ed994e0))
* **generate:** fill CALL arguments the layout index misses; branch dynamic CALL mocks per target ([983dd40](https://github.com/Landparty/mocky-mock/commit/983dd40d39d383826063e785598187270aa17698))
* same-kind nesting in clause bodies; clean removes staged copybook copies ([0829769](https://github.com/Landparty/mocky-mock/commit/0829769cdf0b0f4ac88d2ef5f81ca1a88ab555f3))
* same-kind nesting in clause bodies; clean removes staged copybook copies ([7cb8399](https://github.com/Landparty/mocky-mock/commit/7cb83996adcb2f9ae1b77dd40bbc9c29c020a004))
* **splicer:** mock boundaries nested in another boundary's clause body ([546a3c8](https://github.com/Landparty/mocky-mock/commit/546a3c840c17ffa816653d9c71046ee4fc3fe828))
* **splicer:** mock boundaries nested in another boundary's clause body ([d831283](https://github.com/Landparty/mocky-mock/commit/d83128375b6502f566492cfcc1eb9e9b6663c1cb))
* support GOBACK/STOP RUN inside SECTION members ([b720411](https://github.com/Landparty/mocky-mock/commit/b7204114464cde498cfea94ac4c56745546a3764))
* **sweep:** per-category sweep report with a diff against the last run ([1e05273](https://github.com/Landparty/mocky-mock/commit/1e05273ea715e35fe2ffd4db2f19fe9f576bcf9f))
* **sweep:** per-category sweep report with a diff against the last run ([68c7b43](https://github.com/Landparty/mocky-mock/commit/68c7b43f5121bb46302f2006a9fcc8672d92ef2a))


### Bug Fixes

* **cli:** take a .cut program argument as the suite in every command ([bca0815](https://github.com/Landparty/mocky-mock/commit/bca0815f2373a52d848bd1242ed4aa34eb2a947f))
* close six gaps found in the post-[#367](https://github.com/Landparty/mocky-mock/issues/367) bug hunt ([ccb25fd](https://github.com/Landparty/mocky-mock/commit/ccb25fdc8e9a6393951467256d9b08bd498ccdd1))
* close six gaps found in the post-[#367](https://github.com/Landparty/mocky-mock/issues/367) bug hunt ([85ebca9](https://github.com/Landparty/mocky-mock/commit/85ebca9d49a0f293594b8d2c4cd18d412d46162b))
* **copybooks:** name the missing member and point at near-miss files ([4d37941](https://github.com/Landparty/mocky-mock/commit/4d37941d93aa94622cbc34b58218c2ee15b724b7))
* **debug:** report the line a breakpoint was bound to ([fd3cd20](https://github.com/Landparty/mocky-mock/commit/fd3cd206abc2060eec2454b0557d0c887db7cf16))
* **deps:** adopt cobol-parser 3.1 and lift the &lt;3.1 cap ([f366dc5](https://github.com/Landparty/mocky-mock/commit/f366dc547806e7a5c69b78a3ccdcf8c61903c502))
* **deps:** adopt cobol-parser 3.1 and lift the &lt;3.1 cap ([d1ef44a](https://github.com/Landparty/mocky-mock/commit/d1ef44a236f6f45181d23d09fdd5856dad6558ea))
* **dsl:** refuse an EXPECT value that starts with a relational symbol ([cc23034](https://github.com/Landparty/mocky-mock/commit/cc2303492b70eca6ac9a32804c46c9e7869665f1))
* **expect:** compare a numeric-edited field by value under DECIMAL-POINT IS COMMA ([f5a0487](https://github.com/Landparty/mocky-mock/commit/f5a048704c01031ef58109cc63ed6fca80812a13))
* **generate:** don't copy an AT END clause that PERFORMs into a MOCK READ body ([783e144](https://github.com/Landparty/mocky-mock/commit/783e144bcd0f3ee014ba5d4f6141ce70222d1572))
* **generate:** stub a subprogram output set only through its 88s ([2d3ae92](https://github.com/Landparty/mocky-mock/commit/2d3ae92baa4181955764f130a98a979f8ef94211))
* **mutate:** don't call a zero-then-add swap on a binary field equivalent ([2025f40](https://github.com/Landparty/mocky-mock/commit/2025f4079026eec2cc7e946fe41f85dc9a7fb338))
* no SET in generated case setup; splice driver after a wrapped PROCEDURE DIVISION header ([dbc8114](https://github.com/Landparty/mocky-mock/commit/dbc8114cb1d76e7515ca2f443aecbd3fed41b8ab))
* **reachability:** swap the per-program memo as one tuple ([54d0679](https://github.com/Landparty/mocky-mock/commit/54d0679a17e72fcc3271b896acec2a20b66c059e))
* refuse section ranges that run an unchecked member ([2f7f35e](https://github.com/Landparty/mocky-mock/commit/2f7f35e4607854757ee883ced55586a51c346ba9))
* sweep blockers: sectioned terminators, UNTIL loops, copybook hints, generate speed ([1504ae9](https://github.com/Landparty/mocky-mock/commit/1504ae94ca6e8e94a6ab4388e69d3c22aaaec1b6))
* sweep defects (SET in case setup, wrapped PROCEDURE DIVISION header); support GOBACK/STOP RUN in SECTION members ([3599dcb](https://github.com/Landparty/mocky-mock/commit/3599dcb3d2168f9115c25d7cc6a9ad916a6fc906))
* **terminators:** plan the sectioned GO TO-exit layout and PERFORM UNTIL loops ([05c649f](https://github.com/Landparty/mocky-mock/commit/05c649f5ddcd5983071a43c783995ef458e1555b))
* XML PARSE processing procedure members get no section mode ([2a86c00](https://github.com/Landparty/mocky-mock/commit/2a86c00af6a3b73eeada70167c33e955fe6cb4ea))


### Performance Improvements

* **reachability:** memoize whole-program walks so generate stays near-linear ([8d5c470](https://github.com/Landparty/mocky-mock/commit/8d5c47097112b0f1ca125bcef235eb636d4c8558))


### Documentation

* **okf:** separate the two 2026-10-29 log entries ([09d5378](https://github.com/Landparty/mocky-mock/commit/09d5378ec2ec000f38177359d86d6d125af297a4))
* **skills:** ship cobol-parser's cobol-analysis skill unchanged ([e15b58b](https://github.com/Landparty/mocky-mock/commit/e15b58b7546f12f16372f19792781d2f5a8569ad))

## [0.11.0](https://github.com/Landparty/mocky-mock/compare/v0.11.0...v0.11.0) (2026-10-26)


### Features

* **cics:** synthesize DFHEIBLK EIB fields and generalize LINKAGE neutralization to no-ENTRY programs ([4623b25](https://github.com/Landparty/mocky-mock/commit/4623b254f6dcca13e48904b893b17aa9762afc89))
* **cli:** add --extra-copybook-path, searched after the config list ([38b84ac](https://github.com/Landparty/mocky-mock/commit/38b84ac314d5191c3cf4eeab4811eec4be1d2d80))
* **cli:** AI assistant modes -- hands-on, guided, hands-off ([8aba77f](https://github.com/Landparty/mocky-mock/commit/8aba77f67691177d0fb1bc21776f2405128216d0))
* **cli:** collect --boundaries + mockymock explain (cut editor intelligence, CLI half) ([aee300a](https://github.com/Landparty/mocky-mock/commit/aee300a9fe0eab7ff23f27d87ff92a86bd431d25))
* **cli:** default copybook search directories + actionable not-found hint ([abb0392](https://github.com/Landparty/mocky-mock/commit/abb03921136e8bb8a733f326d61a42bb04d13432))
* **cli:** mockymock doctor -- terminal-native readiness report ([917163a](https://github.com/Landparty/mocky-mock/commit/917163aabb226bf2448ed1cf6ad5ebd7cfb8e3fa))
* **cli:** mockymock doctor -- terminal-native readiness report ([bbd5e9d](https://github.com/Landparty/mocky-mock/commit/bbd5e9d63380941d7d2625ba64f305ce2112be76))
* **cli:** mockymock init -- one command to a scaffold with real assertions ([96c5410](https://github.com/Landparty/mocky-mock/commit/96c54109fef83c6c85322f9dad70285968ba649c))
* **cli:** sibling .cut/.cbl inference, project config file, directory-wide run/lint, grouped help ([bddc5a8](https://github.com/Landparty/mocky-mock/commit/bddc5a850fe3f7a536c8b67aec34e9fdbeb7349b))
* **cli:** sibling inference, project config file, directory-wide run/lint, grouped help ([a6b2aee](https://github.com/Landparty/mocky-mock/commit/a6b2aeead021c3e9ee5663ac3b39f4d86fb37527))
* cobol-testing plugin, cobol-test skill and `mockymock report` ([0e31775](https://github.com/Landparty/mocky-mock/commit/0e3177519f2959638e855483b56e4d9bfba24861))
* **collect:** report boundaries whatever state the suite is in ([97657a6](https://github.com/Landparty/mocky-mock/commit/97657a63ed62ada56e7e58308aada88da6244584))
* **config:** layer a universal cobol.yml under mockymock.toml ([17f99ec](https://github.com/Landparty/mocky-mock/commit/17f99ec17ef6ee167f632ea71fa86ae04d3bfbf2))
* consume cobol-parser from PyPI, publish mockymock to PyPI ([eb76616](https://github.com/Landparty/mocky-mock/commit/eb766167137343d08d4795c2253529c6cf765d0e))
* **dashboard:** show test reports and install/verify the cobol-testing plugin ([d74002f](https://github.com/Landparty/mocky-mock/commit/d74002f49127bdc12aba342abd8aebc8bd244b28))
* **dashboard:** show test reports and install/verify the cobol-testing plugin ([82c6871](https://github.com/Landparty/mocky-mock/commit/82c6871af01f4d75cbedf19b562db9e6720172f8))
* **dsl:** JUnit-style suite hooks (BEFORE-ALL/EACH, AFTER-EACH/ALL) ([fbb1a17](https://github.com/Landparty/mocky-mock/commit/fbb1a17db90b7af7b6dbf2014fb5fe5bec44bd99))
* **dsl:** JUnit-style suite hooks and settable entry parameters ([59c4b7c](https://github.com/Landparty/mocky-mock/commit/59c4b7c70f3b5ff5fc02a2f98a9823c82bd1d85e))
* **dsl:** MOCK CALL ROWS -- one response per call ([d4da70b](https://github.com/Landparty/mocky-mock/commit/d4da70b36d1415bd198e8efd5b122f1af5558d14))
* expand DFHRESP(&lt;condition&gt;) to its EIBRESP value; ignore macros inside EXEC blocks ([f1b6b1e](https://github.com/Landparty/mocky-mock/commit/f1b6b1e100463e6e14e1dde57ecb5bd80ca96bfd))
* EXPECT negation and comparison operators in the .cut DSL ([97aaf0c](https://github.com/Landparty/mocky-mock/commit/97aaf0cd7e85088f646dad075607a42a475ac173))
* **expect:** an unquoted number on a numeric-edited field compares by value ([#350](https://github.com/Landparty/mocky-mock/issues/350)) ([2f12b9f](https://github.com/Landparty/mocky-mock/commit/2f12b9f061c4dd84a11230031bfbf684e0bd1126))
* flag cases that assert nothing; default generate to one case per scenario ([79f3734](https://github.com/Landparty/mocky-mock/commit/79f373484a19c56944edacb1da8e7c33d3d8b6e9))
* **generate:** scaffold CAPTURE ARG, and synthesize the storage it needs ([25076e0](https://github.com/Landparty/mocky-mock/commit/25076e01911e569e165c8a7cf9677adf878434b9))
* **generate:** surface cobol-parser's unverified-scenario verdict in the generated .cut ([bec5a85](https://github.com/Landparty/mocky-mock/commit/bec5a85b02282396330820d270d6daaf3adafe23))
* lead coverage with the original program's number, gate CI on it, and explain stillborn mutants ([073d4f7](https://github.com/Landparty/mocky-mock/commit/073d4f7b9763b96e2725b947ac1d2e5cb4f9aea9))
* **linkage:** entry parameters a test sets, resets and keeps after BEFORE-ALL ([63a115d](https://github.com/Landparty/mocky-mock/commit/63a115d8bb60e36d2aa2683169496436aadb3814))
* **lint:** add --case and --tag to scope per-case checks ([cf9069d](https://github.com/Landparty/mocky-mock/commit/cf9069d11d9a4f51f6040d8e7307d68cf2c73ed1))
* **lint:** boundaries reached only by GO TO fall-through warn instead of refusing ([#351](https://github.com/Landparty/mocky-mock/issues/351)) ([6ac0953](https://github.com/Landparty/mocky-mock/commit/6ac0953864f72513d8937eae16d703f941f80875))
* mock plain-file-form SORT/MERGE (USING ... GIVING ...) ([7872a68](https://github.com/Landparty/mocky-mock/commit/7872a68252773fdd61c3d64e49030658f9116fcf))
* mock SORT/MERGE (USING/GIVING form + RELEASE/RETURN) ([989784e](https://github.com/Landparty/mocky-mock/commit/989784e3d2f17a19da8f3df7f5230de8e0c7d3b2))
* mock SORT/MERGE's INPUT/OUTPUT PROCEDURE form via RELEASE/RETURN ([a32c20e](https://github.com/Landparty/mocky-mock/commit/a32c20ef8b4b4173d9d8bc6108177b41eddd621a))
* **mocks:** one MOCK per file of a multi-file OPEN/CLOSE, each verifiable ([#348](https://github.com/Landparty/mocky-mock/issues/348)) ([056a0dc](https://github.com/Landparty/mocky-mock/commit/056a0dcfafa3287258c98e2687a0d757b2607701))
* **mutate:** coverage gate and --jobs, the two mutation cost levers ([2127755](https://github.com/Landparty/mocky-mock/commit/212775556c6207588f671910b710ecca0dd94d7b))
* **mutate:** report provably equivalent mutants and leave them out of the score ([#349](https://github.com/Landparty/mocky-mock/issues/349)) ([5e0f837](https://github.com/Landparty/mocky-mock/commit/5e0f837e8d73717a8c32bdbf6a5f7f33301e785b))
* **refusal,generate:** suggested_fix on UNMOCKED_* refusals + generate --fill ([314ce6d](https://github.com/Landparty/mocky-mock/commit/314ce6d47b78469170dae5d135e07003bf3bf56e))
* **refusal:** pin every Enterprise COBOL program type; honest nested-program and DECLARATIVES refusals ([09803b0](https://github.com/Landparty/mocky-mock/commit/09803b04571a6718e7c68a720bb4e51b16565c70))
* refuse or mock every COBOL dependency cobol-parser now parses ([0fc46f2](https://github.com/Landparty/mocky-mock/commit/0fc46f28a6ed2a5852874d85300b320646c215eb))
* **report:** add cobol-parser program analysis to the HTML report ([1d90600](https://github.com/Landparty/mocky-mock/commit/1d9060082a0e735962632431040af0935a0df8f6))
* **report:** add cobol-parser program analysis to the HTML report ([e3038f4](https://github.com/Landparty/mocky-mock/commit/e3038f4baba1439722eb7155a8b659bd07a1235a))
* **report:** enhance HTML report styling and improve arm line descriptions ([9533ded](https://github.com/Landparty/mocky-mock/commit/9533ded08ff2891be33935c427f44edd894c82d5))
* **report:** enhance scenario gap reporting and clarify leading sentences handling ([0230fb6](https://github.com/Landparty/mocky-mock/commit/0230fb6ebacdc552f8c556e29892cb21101db93d))
* **report:** list every boundary and the tests that mock it ([a3108f4](https://github.com/Landparty/mocky-mock/commit/a3108f407ae43c81894f0429e4b1eb15005217a3))
* **report:** make the test report easier to read ([2237d16](https://github.com/Landparty/mocky-mock/commit/2237d160af793fb84b8c081439183b45d0e90fd2))
* **report:** make the test report easier to read ([a61be5a](https://github.com/Landparty/mocky-mock/commit/a61be5a0cbd66943309fa308bdaa6b1294b03c7d))
* **report:** one .mockymock/ folder per suite, reused run/mutate results, clean, batch journal ([#352](https://github.com/Landparty/mocky-mock/issues/352), [#353](https://github.com/Landparty/mocky-mock/issues/353)) ([cd83bb2](https://github.com/Landparty/mocky-mock/commit/cd83bb25a68fe2ab14d26122192e043562af34db))
* **runtime:** native GnuCOBOL toolchain backend, selected by MOCKYMOCK_GNUCOBOL_HOME ([8d8c36d](https://github.com/Landparty/mocky-mock/commit/8d8c36df1d6268f4504d4790183fd435cae59ac4))
* **setup:** say in setup --help that a GnuCOBOL home switches to the native backend ([b4a20ec](https://github.com/Landparty/mocky-mock/commit/b4a20ec988cb43da4d1156ae93d2b3276e69df56))
* several suites per program, and suites under tests/ ([1f91d56](https://github.com/Landparty/mocky-mock/commit/1f91d56d905d765a610765a2cb8894ac0c2dfb28))
* **skills:** install and verify the cobol-testing skills for GitHub Copilot ([2cde971](https://github.com/Landparty/mocky-mock/commit/2cde971fc3a907fcf3dc4d77f31cc3d278c16fa2))
* **skills:** install and verify the cobol-testing skills for GitHub Copilot ([76e0f38](https://github.com/Landparty/mocky-mock/commit/76e0f38e9e7619f2af66f7f04799980f1edd2ec4))
* **skills:** install the cobol-testing plugin from a local directory ([1d46710](https://github.com/Landparty/mocky-mock/commit/1d467103776c4e04a415a36955cbd5d3c461e5e9))


### Bug Fixes

* ACCEPT FROM DATE with format, control bytes in stdout, EXPECT comment periods, paren-aware ROWS split, early-crash JUnit, provider header scan ([2451ebf](https://github.com/Landparty/mocky-mock/commit/2451ebf2e9abc6fdf2d6c5421cbe56301d9a650d))
* address four review findings on the capture/export/coverage work ([1a8daea](https://github.com/Landparty/mocky-mock/commit/1a8daea47cce20c57a29b980d899f94c36417879))
* **analysis:** keep the qualifiers of a FILE STATUS IS field ([59065cc](https://github.com/Landparty/mocky-mock/commit/59065cc7e0a570cca503051e57731709e3abbc96)), closes [#266](https://github.com/Landparty/mocky-mock/issues/266)
* **analysis:** key an ACCEPT site on its target's data-name ([ecaa9f3](https://github.com/Landparty/mocky-mock/commit/ecaa9f3664b862a48a2d49780df99f04925a01e2)), closes [#311](https://github.com/Landparty/mocky-mock/issues/311)
* **analysis:** neutralize EXIT PROGRAM like GOBACK in the program under test ([8c52170](https://github.com/Landparty/mocky-mock/commit/8c52170f200503501e0ed8ebb7fa884c7ace3435)), closes [#212](https://github.com/Landparty/mocky-mock/issues/212)
* **analysis:** refuse a case that reaches a paragraph name defined in two SECTIONs ([f92a779](https://github.com/Landparty/mocky-mock/commit/f92a77932ad5ba2ee8ad3b57b1b55de9d6dc7b54)), closes [#284](https://github.com/Landparty/mocky-mock/issues/284)
* **analysis:** refuse MOCK SECTION when its paragraphs are referenced qualified ([83c9d93](https://github.com/Landparty/mocky-mock/commit/83c9d9399608c69ca51eeb1616ac61d9b0a819ee)), closes [#293](https://github.com/Landparty/mocky-mock/issues/293)
* **analysis:** refuse terminators a .cut PERFORM THRU range would run past ([6d2ea90](https://github.com/Landparty/mocky-mock/commit/6d2ea90e610bbb108032370ecef108d4461b9f7d)), closes [#211](https://github.com/Landparty/mocky-mock/issues/211)
* **analysis:** resolve botched merge leaving stale refusal package ([d802f0c](https://github.com/Landparty/mocky-mock/commit/d802f0c3801e8878dc3c963d48703dccee919cc2))
* **analysis:** resolve lowercase PERFORM / GO TO targets ([ab63305](https://github.com/Landparty/mocky-mock/commit/ab63305b72c04005e32ef0cdb58f02b689518513))
* **analysis:** resolve lowercase PERFORM / GO TO targets ([0c7aed0](https://github.com/Landparty/mocky-mock/commit/0c7aed06aa696e8d1b92ab64df16d488a342cf3a))
* **analysis:** resolve transitive GO-TO-exit fallthrough chains to a fixpoint ([46aa88a](https://github.com/Landparty/mocky-mock/commit/46aa88a8f313053712b4a4d91414e24db1522caf))
* **analysis:** skip the GO TO exit rewrite when a PERFORM lacks the THRU ([82f7ce5](https://github.com/Landparty/mocky-mock/commit/82f7ce53a67f2f5b397d2f21a30c09044445e189)), closes [#213](https://github.com/Landparty/mocky-mock/issues/213)
* **analysis:** stop GO TO fall-through cascade past a safely-entered section ([63b8e69](https://github.com/Landparty/mocky-mock/commit/63b8e69b40bfce096364f163a98785250c1bfaea))
* **analysis:** stop GO-TO-exit fall-through cascade in reachability gates ([25965c0](https://github.com/Landparty/mocky-mock/commit/25965c099e8d3499ba34879ede51586486ae7a79))
* **analysis:** stop the terminator planner's GO TO fall-through walk at a safe section's end ([3efbeb1](https://github.com/Landparty/mocky-mock/commit/3efbeb1692f479d58a61536792681459f60b2a6f)), closes [#259](https://github.com/Landparty/mocky-mock/issues/259)
* **analysis:** treat a PROCEDURE DIVISION EXEC SQL DECLARE as a declaration ([3f491ae](https://github.com/Landparty/mocky-mock/commit/3f491aeb73f6ede1f2002f53e6881e94e1442d6d)), closes [#267](https://github.com/Landparty/mocky-mock/issues/267)
* **analysis:** type exact_counts' paragraph table as Any for mypy ([eb5bf87](https://github.com/Landparty/mocky-mock/commit/eb5bf87156a473c55b0d090190257d7086c2b4d7))
* back UNSUPPORTED_DECLARATIVES with a USE-statement fallback ([f1d24ca](https://github.com/Landparty/mocky-mock/commit/f1d24ca528098565f3fad41714b63eb77e27606d))
* bug hunt round 11 -- mutation, export, DSL, JUnit, bundle, debugger, run_binary ([1841aa2](https://github.com/Landparty/mocky-mock/commit/1841aa2d6094a171e2516891545784824f844659))
* bug hunt round 12 -- source encoding, --fill CRLF, debugger values, SQL INCLUDE, provenance ([d39d5b0](https://github.com/Landparty/mocky-mock/commit/d39d5b0356bb51327308f31277b30b3b9a6876b3))
* **checks:** compile D lines as code under WITH DEBUGGING MODE ([eb7a75b](https://github.com/Landparty/mocky-mock/commit/eb7a75b50119a42051b39460c24358e087f0caf4)), closes [#274](https://github.com/Landparty/mocky-mock/issues/274)
* **checks:** judge shared-mock reach over the whole suite, not the selection ([8c682d5](https://github.com/Landparty/mocky-mock/commit/8c682d54e52987b6f7e028838122ac5200a73547)), closes [#250](https://github.com/Landparty/mocky-mock/issues/250)
* **checks:** refuse .cut data-names the program does not declare ([4c7025e](https://github.com/Landparty/mocky-mock/commit/4c7025e457993827fac82f6ae17212fc246ebfcb)), closes [#204](https://github.com/Landparty/mocky-mock/issues/204)
* **checks:** refuse free-format COBOL instead of column-chopping it ([cc2f8ef](https://github.com/Landparty/mocky-mock/commit/cc2f8effc02dc78c38978a5d7e3f5b7993dc3e9c)), closes [#210](https://github.com/Landparty/mocky-mock/issues/210)
* **checks:** synthesize DFHEIBLK/DLIDIB when only the .cut names a field ([d2ba9ad](https://github.com/Landparty/mocky-mock/commit/d2ba9ad691d280b1583a0f23b9bc4786c0676377)), closes [#269](https://github.com/Landparty/mocky-mock/issues/269)
* **cics:** COBOL-aware word boundaries and case-insensitive EIB/DFHCOMMAREA/DFHRESP matching ([cc07964](https://github.com/Landparty/mocky-mock/commit/cc07964f66a6d7a1e225f775d5d0d81da29eb1c0))
* **cics:** emulate EXEC CICS HANDLE/IGNORE CONDITION instead of mocking it ([0805938](https://github.com/Landparty/mocky-mock/commit/0805938ef6db93454a66e2d55fd9dd38086c5cfd)), closes [#268](https://github.com/Landparty/mocky-mock/issues/268)
* classify ADDRESS OF per statement, not per line, in the LINKAGE fold gate ([8a071ca](https://github.com/Landparty/mocky-mock/commit/8a071ca3a3cc25365202e28746d732d06c636432))
* **clause-bodies:** refuse unterminated nested phrases, not phrase words ([3422ed5](https://github.com/Landparty/mocky-mock/commit/3422ed5e4241a21f722941ee1a0e125e77630d80)), closes [#326](https://github.com/Landparty/mocky-mock/issues/326)
* **clause-bodies:** skip inline *&gt; comments when scanning clause bodies ([d4bd42c](https://github.com/Landparty/mocky-mock/commit/d4bd42c80326c4e66ded09f22e3588e248754101)), closes [#327](https://github.com/Landparty/mocky-mock/issues/327)
* **cli:** collect --boundaries resolves copybooks like lint and run ([792e57f](https://github.com/Landparty/mocky-mock/commit/792e57f1ca3449925b57219d97e3db8d26b2e6fc)), closes [#200](https://github.com/Landparty/mocky-mock/issues/200)
* **cli:** create a report file's parent directory, report write failures on stderr ([06747e8](https://github.com/Landparty/mocky-mock/commit/06747e84436f603aa985fe5ce4adab886aec3e53)), closes [#257](https://github.com/Landparty/mocky-mock/issues/257)
* **cli:** fail run/lint over a directory on a broken PROGRAM line ([0b6085a](https://github.com/Landparty/mocky-mock/commit/0b6085aa2afa51c349fa9e4a938c4a10217767af)), closes [#303](https://github.com/Landparty/mocky-mock/issues/303)
* **cli:** find suites in a tests folder outside the project root ([226abc1](https://github.com/Landparty/mocky-mock/commit/226abc1d7fb1ce78f30217a4be9be6bb9927d0e1)), closes [#294](https://github.com/Landparty/mocky-mock/issues/294)
* **cli:** find WORKING-STORAGE/PROCEDURE headers with any whitespace between words ([e4947af](https://github.com/Landparty/mocky-mock/commit/e4947af338bfaa2b681fb53b429538f708a25e2d)), closes [#305](https://github.com/Landparty/mocky-mock/issues/305)
* **cli:** give each of a program's several suites its own report file ([fc1344e](https://github.com/Landparty/mocky-mock/commit/fc1344e55aa738495dcc2f4b92e412e2e3e52e12))
* **cli:** give each of a program's several suites its own report file ([5c2b067](https://github.com/Landparty/mocky-mock/commit/5c2b067774998a8629542d322ff4e48f46d84b92))
* **cli:** keep collect --json errors machine-readable ([95790c9](https://github.com/Landparty/mocky-mock/commit/95790c96907b536c181c91630ddbca2d22116eb5)), closes [#309](https://github.com/Landparty/mocky-mock/issues/309)
* **cli:** pair a dotted program with the suite generate wrote for it ([3db37f8](https://github.com/Landparty/mocky-mock/commit/3db37f8e5d5114cb43ecc97355bcef55124ddc01)), closes [#289](https://github.com/Landparty/mocky-mock/issues/289)
* **cli:** refuse --timeout below 1 second ([c590901](https://github.com/Landparty/mocky-mock/commit/c5909010f806bbe68e6773372677a4a33560666b)), closes [#306](https://github.com/Landparty/mocky-mock/issues/306)
* **cli:** report refusal lines in the .cbl the user has open ([213b6e4](https://github.com/Landparty/mocky-mock/commit/213b6e4a281d59c691d4b59f1319d08070d21220)), closes [#241](https://github.com/Landparty/mocky-mock/issues/241)
* **cli:** review follow-up for [#112](https://github.com/Landparty/mocky-mock/issues/112) (with-data copybook hint) ([2e61939](https://github.com/Landparty/mocky-mock/commit/2e61939718e5cffcc722c47e6e51b71408413a70))
* **cli:** review follow-ups across the CLI PRs ([#111](https://github.com/Landparty/mocky-mock/issues/111)-[#116](https://github.com/Landparty/mocky-mock/issues/116)) ([2ba1361](https://github.com/Landparty/mocky-mock/commit/2ba13616da7de52ddfa3d54d59c31f5987fd62ac))
* **cli:** review follow-ups for [#111](https://github.com/Landparty/mocky-mock/issues/111) (rebuild, config, discovery, reports) ([c7fa5b4](https://github.com/Landparty/mocky-mock/commit/c7fa5b4031a2cc1627d78475a44fcea0638ff08e))
* **cli:** skip suites with no selected case when running a project with --tag/--case ([2abe68b](https://github.com/Landparty/mocky-mock/commit/2abe68bc68364c98572e36981b088c5ceed3cf31)), closes [#254](https://github.com/Landparty/mocky-mock/issues/254)
* **cli:** validate generate/init/suites --name as one plain word ([624c4ea](https://github.com/Landparty/mocky-mock/commit/624c4eac29453c8726c2a64068f497d28d5c31d9)), closes [#336](https://github.com/Landparty/mocky-mock/issues/336)
* correct VERIFY syntax in design note; cover all three exhaustion paths ([d343d9b](https://github.com/Landparty/mocky-mock/commit/d343d9b798e7ce0990b6fd4faf1011e47f6bbcd4))
* **coverage:** count a replaced boundary or GOBACK as the line it was ([e7a0d9f](https://github.com/Landparty/mocky-mock/commit/e7a0d9f8fed06834000ac9035bf7c9aecf88cc1b)), closes [#297](https://github.com/Landparty/mocky-mock/issues/297)
* **debug:** decode b_-only binary/signed items from PICTURE and USAGE ([e41cd56](https://github.com/Landparty/mocky-mock/commit/e41cd56a1e7c7302828c09ecbdce2aac976c68af)), closes [#168](https://github.com/Landparty/mocky-mock/issues/168)
* **debug:** decode numeric-edited, COMP-1 and COMP-2 fields ([e24805c](https://github.com/Landparty/mocky-mock/commit/e24805c3522d81daa602ba92fcb965b09f23b5ff)), closes [#207](https://github.com/Landparty/mocky-mock/issues/207)
* **debug:** decode P-scaled numeric items to the value they hold ([d85743b](https://github.com/Landparty/mocky-mock/commit/d85743b70f934e34df12f9d946731fdccb92d07b)), closes [#295](https://github.com/Landparty/mocky-mock/issues/295)
* **debug:** make Step Over and Step Out honor PERFORM boundaries ([f1eb953](https://github.com/Landparty/mocky-mock/commit/f1eb9537dc5ae3abe54286de64f04ceac5513b32))
* **debug:** make Step Over and Step Out honor PERFORM boundaries ([b310416](https://github.com/Landparty/mocky-mock/commit/b310416d9287e88a2d67636a1d62e52527f14f9b)), closes [#167](https://github.com/Landparty/mocky-mock/issues/167)
* **debug:** match DAP breakpoints by source path ([63abb5e](https://github.com/Landparty/mocky-mock/commit/63abb5e22d08564bec62e406e5e8e3c96020c5f4))
* **debug:** name call-stack paragraphs in original-file lines ([6fe6958](https://github.com/Landparty/mocky-mock/commit/6fe695851d76e7615a34dcbb7cf70ce9c2504ac3)), closes [#256](https://github.com/Landparty/mocky-mock/issues/256)
* **debug:** show an unreadable item instead of failing Variables ([460fcec](https://github.com/Landparty/mocky-mock/commit/460fcecc4aa0f3e0d202c4b2ecc383e01f9c30ed)), closes [#318](https://github.com/Landparty/mocky-mock/issues/318)
* **deps:** allow cobol-parser 3.x and lock to 3.0.0 ([7df54d1](https://github.com/Landparty/mocky-mock/commit/7df54d1a960f87403f0f7aaac9ea2501238fc7ed))
* **deps:** allow cobol-parser 3.x and lock to 3.0.0 ([5daf46d](https://github.com/Landparty/mocky-mock/commit/5daf46d366d1e21472e98376f99bdeb4550b30d1))
* **deps:** cap cobol-parser below 3.1 ([7307467](https://github.com/Landparty/mocky-mock/commit/730746705c4de89ff8755361c01c013e96220951))
* **deps:** cap cobol-parser below 3.1 ([0dad467](https://github.com/Landparty/mocky-mock/commit/0dad467e56b296b97926d1ee3682ff3b7891c92b))
* **driver:** cap the UT-TESTSUITE- paragraph name at 30 characters ([95d4197](https://github.com/Landparty/mocky-mock/commit/95d4197e1bc5706709174b6736fdbb73ad6f0fa3)), closes [#279](https://github.com/Landparty/mocky-mock/issues/279)
* **driver:** guard a negated EXPECT with an AND/OR tail on the un-negated condition ([5437711](https://github.com/Landparty/mocky-mock/commit/5437711290957af40a7df78d35c00a1389e418c4)), closes [#339](https://github.com/Landparty/mocky-mock/issues/339)
* **driver:** reset RETURN-CODE per case and before STOP RUN ([#140](https://github.com/Landparty/mocky-mock/issues/140)) ([988aef5](https://github.com/Landparty/mocky-mock/commit/988aef5960a8dd9746b17efc65310bac724a401d))
* **dsl:** accept a .cut file saved with a UTF-8 BOM ([ed64adf](https://github.com/Landparty/mocky-mock/commit/ed64adf06513a186be903e3d446fcfc0cdcfed73)), closes [#198](https://github.com/Landparty/mocky-mock/issues/198)
* **dsl:** accept lowercase PERFORM names in a .cut, quiet the key-mismatch warning for unmockable sites ([6860e88](https://github.com/Landparty/mocky-mock/commit/6860e88d8d47ef3396cc85449104a07d7ab4b3c1)), closes [#164](https://github.com/Landparty/mocky-mock/issues/164)
* **dsl:** accept OF/IN-qualified data-names in MOVE, EXPECT, CAPTURE and stubs ([28a82fd](https://github.com/Landparty/mocky-mock/commit/28a82fdb3c03a8ec89fe6a86003c15fdf504ce80)), closes [#252](https://github.com/Landparty/mocky-mock/issues/252)
* **dsl:** accept TAGS after USING PROVIDER on a TESTCASE line ([127fced](https://github.com/Landparty/mocky-mock/commit/127fcedd1832e3f396e12a47e38805769506209f)), closes [#329](https://github.com/Landparty/mocky-mock/issues/329)
* **dsl:** lowercase PERFORM names in a .cut, quieter key-mismatch warning ([8b9b339](https://github.com/Landparty/mocky-mock/commit/8b9b33949f42546286c525f764a9ce2d0343b8d0))
* **dsl:** refuse a MOCK body that PERFORMs, GOes TO or terminates ([9c0a3b7](https://github.com/Landparty/mocky-mock/commit/9c0a3b7eafe4d613e60df78c2c25f12f97282ed4)), closes [#287](https://github.com/Landparty/mocky-mock/issues/287)
* **dsl:** refuse a MOVE value ending in a sentence period ([53372bc](https://github.com/Landparty/mocky-mock/commit/53372bcf6fbf4e029ba4a7018d1bf38ba20fb7b7)), closes [#197](https://github.com/Landparty/mocky-mock/issues/197)
* **dsl:** refuse an empty TESTCASE name ([77342cd](https://github.com/Landparty/mocky-mock/commit/77342cdb50c0510735c5feb81f9103891e4b7cf9)), closes [#308](https://github.com/Landparty/mocky-mock/issues/308)
* **dsl:** refuse an unterminated quoted literal in a .cut value ([3d9cbd1](https://github.com/Landparty/mocky-mock/commit/3d9cbd1ea37fb3fbed744875e88eab1fccda8ecc)), closes [#270](https://github.com/Landparty/mocky-mock/issues/270)
* **dsl:** refuse PROVIDER placeholders in hook steps and hook MOCK bodies ([c476a21](https://github.com/Landparty/mocky-mock/commit/c476a2103f47b6105ed00b246624d9be77aeadd3)), closes [#227](https://github.com/Landparty/mocky-mock/issues/227)
* **dsl:** sequence MOCK ACCEPT and end a loop waiting on its sentinel ([647a0ad](https://github.com/Landparty/mocky-mock/commit/647a0ad7767b5137dae90d4c291c58b0b8d0df43)), closes [#263](https://github.com/Landparty/mocky-mock/issues/263)
* **dsl:** sequence MOCK CICS with ROWS/TERMINAL; expand DFHRESP in .cut text ([8978fd9](https://github.com/Landparty/mocky-mock/commit/8978fd97851ee717a1ba92628be63501f0e828ea))
* **dsl:** sequence MOCK CICS with ROWS/TERMINAL; expand DFHRESP in .cut text ([00ddb62](https://github.com/Landparty/mocky-mock/commit/00ddb628e40aa4f3244034eea3ab619bef539ad5)), closes [#169](https://github.com/Landparty/mocky-mock/issues/169)
* **dsl:** strip trailing *&gt; comments from parsed .cut lines ([c11f4bb](https://github.com/Landparty/mocky-mock/commit/c11f4bb713e3618fcc885db0795cef8d4386028d)), closes [#236](https://github.com/Landparty/mocky-mock/issues/236)
* end looped MQGET/CBLTDLI mocks, restore OCCURS VALUEs, show unwrapped debugger vars ([33db19b](https://github.com/Landparty/mocky-mock/commit/33db19be00dacd3737123b56361d6e5cc1dab91b))
* end looped MQGET/CBLTDLI mocks, restore OCCURS VALUEs, show unwrapped vars ([#156](https://github.com/Landparty/mocky-mock/issues/156)) ([a54f92b](https://github.com/Landparty/mocky-mock/commit/a54f92b9f758d69c61897167d9d1b9ce25a2e55f))
* EXEC mock key spacing, CAPTURE of literal arguments, bundle expectations for PIC X, DIVIDE REMAINDER mutants ([a530a84](https://github.com/Landparty/mocky-mock/commit/a530a841ebd9cd142e51b0b82a905ed61a20ca2a))
* EXEC mock keys match on name boundaries, FILE STATUS for multi-file OPEN/CLOSE, phantom EXEC paragraphs, dashboard Host check ([529102e](https://github.com/Landparty/mocky-mock/commit/529102e35b415f95e06dfb192a99bafa4a59c4e0))
* **explain:** catalogue UNRESOLVED_FLOW_MOCK_TARGET, UNRESOLVED_CAPTURE_TARGET, COLUMN_OVERFLOW ([60bfa55](https://github.com/Landparty/mocky-mock/commit/60bfa5500f97943ee8296b768216892ef9048054))
* **export:** continue a long literal instead of refusing the line ([4c9838f](https://github.com/Landparty/mocky-mock/commit/4c9838fea95c2282d80723afcaf80551f73763d5))
* **export:** fit column 72 in UTF-8 bytes, not characters ([e16a12e](https://github.com/Landparty/mocky-mock/commit/e16a12e58aeaee83a641d07ca3a603bf33ec214b)), closes [#298](https://github.com/Landparty/mocky-mock/issues/298)
* **export:** keep the CBL/PROCESS card first with ID DIVISION ([0cca970](https://github.com/Landparty/mocky-mock/commit/0cca970cbab81f50155ecb6d67f1472b7d901c27)), closes [#276](https://github.com/Landparty/mocky-mock/issues/276)
* **export:** keep the IBM-legal redirect instead of BASED rebinds ([5918f73](https://github.com/Landparty/mocky-mock/commit/5918f736d47feed55186274c89a9c9d68b7f0dec)), closes [#321](https://github.com/Landparty/mocky-mock/issues/321)
* **export:** name the two literal-continuation failure modes apart ([26e3624](https://github.com/Landparty/mocky-mock/commit/26e36249ad669f015d801a7d9b63fa8f21f4d745))
* **export:** tell the clause-body lift about the restored sequence area ([549553f](https://github.com/Landparty/mocky-mock/commit/549553f8cdeb67f807b007921f9b5fbdff3a17ad)), closes [#325](https://github.com/Landparty/mocky-mock/issues/325)
* **export:** wrap over-long lines instead of refusing, and name the real overflow source ([c7fef8f](https://github.com/Landparty/mocky-mock/commit/c7fef8f920da5ae7ce395d1977d90755d1670159))
* field-run follow-ups to [#346](https://github.com/Landparty/mocky-mock/issues/346), [#347](https://github.com/Landparty/mocky-mock/issues/347), [#349](https://github.com/Landparty/mocky-mock/issues/349) and [#351](https://github.com/Landparty/mocky-mock/issues/351) ([4b2f9ae](https://github.com/Landparty/mocky-mock/commit/4b2f9ae0c2cfd7a58725d282139831f6af852bdc))
* field-run follow-ups to [#346](https://github.com/Landparty/mocky-mock/issues/346), [#347](https://github.com/Landparty/mocky-mock/issues/347), [#349](https://github.com/Landparty/mocky-mock/issues/349) and [#351](https://github.com/Landparty/mocky-mock/issues/351) ([079fb97](https://github.com/Landparty/mocky-mock/commit/079fb970c19f15703f08b524a0240a9d1b4cbd82))
* field-run framework limits (THRU scaffold, end-of-program trap, copybook folders, libxml noise) ([85c7fdc](https://github.com/Landparty/mocky-mock/commit/85c7fdc4f0c9332073a940def1a8673f7522020c))
* **flow-mocks:** refuse a MOCK PARAGRAPH inside a SORT/XML procedure THRU range ([9d447eb](https://github.com/Landparty/mocky-mock/commit/9d447eba1db3cbeb1ea137525d8329f2566829f6)), closes [#261](https://github.com/Landparty/mocky-mock/issues/261)
* framework limits from the legacy-application field run ([a8bbd79](https://github.com/Landparty/mocky-mock/commit/a8bbd7938af32e9ecc7fa3ea008af34319eee85a))
* generate with a pre-paragraph mainline, literal-argument captures in generate, debugger value decoding ([7f3b7b5](https://github.com/Landparty/mocky-mock/commit/7f3b7b574f776e92d89288897a8ddb81461c4019))
* **generate:** --fill exits 1 on an unmocked hook boundary it cannot fill ([43ae2f9](https://github.com/Landparty/mocky-mock/commit/43ae2f9689d8d92d25438808f7e7218de71ee7a3)), closes [#208](https://github.com/Landparty/mocky-mock/issues/208)
* **generate,record-expectations:** no MOVE or EXPECT on pointer and INDEX items ([eaacbd5](https://github.com/Landparty/mocky-mock/commit/eaacbd53ece4828639e14e6ac62fae16586bc1ab))
* **generate,record-expectations:** no MOVE or EXPECT on pointer and INDEX items ([b8b53bc](https://github.com/Landparty/mocky-mock/commit/b8b53bcd48436e2ecd77325f7d793132a52788db))
* **generate:** answer a DL/I CALL with a blank PCB status ([67eb4e6](https://github.com/Landparty/mocky-mock/commit/67eb4e661f4eb30d55ea3c48c8264d680b56f450)), closes [#317](https://github.com/Landparty/mocky-mock/issues/317)
* **generate:** answer CICS RESP and RESP2 with NORMAL on the happy path ([4c3e9b0](https://github.com/Landparty/mocky-mock/commit/4c3e9b0ae230d90f7dd780b1757d09470c7dd9f6)), closes [#253](https://github.com/Landparty/mocky-mock/issues/253)
* **generate:** answer MQCC_OK / MQRC_NONE in generated MQ mocks ([4e52ff4](https://github.com/Landparty/mocky-mock/commit/4e52ff4a5c76af3d020790b5bbec67c630cbdb83)), closes [#205](https://github.com/Landparty/mocky-mock/issues/205)
* **generate:** cast the program for analyze_file_status_fields instead of a type: ignore ([0356811](https://github.com/Landparty/mocky-mock/commit/0356811b5b799696c6c9c056f0b7eea9dd2ac30e))
* **generate:** demote call counts for sites inside loops or PERFORMed twice ([62444f7](https://github.com/Landparty/mocky-mock/commit/62444f7a48199d2d169b59d06d8c861104dcb673)), closes [#290](https://github.com/Landparty/mocky-mock/issues/290)
* **generate:** don't call a program-supplied CALL a key mismatch ([bee590e](https://github.com/Landparty/mocky-mock/commit/bee590e06294d15bf1d0b249171568fee8a5d57d)), closes [#300](https://github.com/Landparty/mocky-mock/issues/300)
* **generate:** don't count calls from paragraphs the case never reaches ([7084b77](https://github.com/Landparty/mocky-mock/commit/7084b77e794e2fe87839fbd603d07d7b705137d0))
* **generate:** don't count calls from paragraphs the case never reaches ([069c13f](https://github.com/Landparty/mocky-mock/commit/069c13f0438cde26dd2f9f92808145e746817d37))
* **generate:** don't write a loop's control item from a CALL mock ([e0ab8da](https://github.com/Landparty/mocky-mock/commit/e0ab8da9c62e1d6f3e8bda9f00a472883cf99e88)), closes [#286](https://github.com/Landparty/mocky-mock/issues/286)
* **generate:** emit real READ exhaustion arms and stop dropping boundary stub expectations ([9fc8f7d](https://github.com/Landparty/mocky-mock/commit/9fc8f7d83eb57e041b8794fdfc1c9fc755a142e8))
* **generate:** end a CICS browse loop guarded on its own RESP ([ceed9fe](https://github.com/Landparty/mocky-mock/commit/ceed9feefb91465a1a61815f7bf51ca6302e7742)), closes [#316](https://github.com/Landparty/mocky-mock/issues/316)
* **generate:** end a FILE-STATUS-driven READ loop in --with-data suites ([52fdc6f](https://github.com/Landparty/mocky-mock/commit/52fdc6fab6b638f4c6354492419a4b9a85cf40ec))
* **generate:** end a FILE-STATUS-driven READ loop in --with-data suites ([396dd7d](https://github.com/Landparty/mocky-mock/commit/396dd7dac866a55ed361335c95e43e2c34905055))
* **generate:** end a looped MQGET whose guard flag is set on its reply ([f651ac7](https://github.com/Landparty/mocky-mock/commit/f651ac7ea89cdf530a0135a3575b6464fcb6fb9c)), closes [#188](https://github.com/Landparty/mocky-mock/issues/188)
* **generate:** end a placeholder READ/RETURN mock's AT END loop ([48b4ca4](https://github.com/Landparty/mocky-mock/commit/48b4ca4bf9084767cef8c98e13051415be1f6b3a)), closes [#302](https://github.com/Landparty/mocky-mock/issues/302)
* **generate:** end a priming-read loop and count one READ stream once ([0380cde](https://github.com/Landparty/mocky-mock/commit/0380cdeed39631aa167408d97c81d87f963f6058))
* **generate:** end an EXEC DLI get loop primed by a GN before it ([c6f7120](https://github.com/Landparty/mocky-mock/commit/c6f7120d2d4c1144ae1f740703c2b08dc14eb1a4)), closes [#315](https://github.com/Landparty/mocky-mock/issues/315)
* **generate:** enter a section-structured program at its main SECTION ([7abb4ad](https://github.com/Landparty/mocky-mock/commit/7abb4ad09877862076bc975fcf27f2ffe1d18346)), closes [#238](https://github.com/Landparty/mocky-mock/issues/238)
* **generate:** fail when the scaffold's own cases are refused ([517699d](https://github.com/Landparty/mocky-mock/commit/517699d9e1ad7040871628df104a4044f23cd322)), closes [#231](https://github.com/Landparty/mocky-mock/issues/231)
* **generate:** give prefix-nested EXEC sites one MOCK key ([c03f3e2](https://github.com/Landparty/mocky-mock/commit/c03f3e20e692c863f18d968bbba8dc6dd3db8c09)), closes [#248](https://github.com/Landparty/mocky-mock/issues/248)
* **generate:** key a multi-file OPEN/CLOSE so one MOCK covers its sibling sites ([fb9dd6e](https://github.com/Landparty/mocky-mock/commit/fb9dd6e0ef4ce3566d44097d6108c2e60982a49c)), closes [#312](https://github.com/Landparty/mocky-mock/issues/312)
* **generate:** leave a CICS command's input operands out of its mock ([1e08394](https://github.com/Landparty/mocky-mock/commit/1e08394a3ba47464bc503a147b096cb182ed1afd)), closes [#222](https://github.com/Landparty/mocky-mock/issues/222)
* **generate:** let [#188](https://github.com/Landparty/mocky-mock/issues/188)'s one-hop reply rule end MQGET drain loops ([3c34642](https://github.com/Landparty/mocky-mock/commit/3c3464269b1a9fc2c7d5ec0ccecf3f2ef7dec56c))
* **generate:** mock a looped cursor FETCH with ROWS so its loop ends ([#141](https://github.com/Landparty/mocky-mock/issues/141)) ([25931d9](https://github.com/Landparty/mocky-mock/commit/25931d9191c136f350d41e0d692d62848a997563))
* **generate:** one VERIFY per mocked key, summing the bundle's per-site counts ([#142](https://github.com/Landparty/mocky-mock/issues/142)) ([6de6a11](https://github.com/Landparty/mocky-mock/commit/6de6a111b3e2686ac00dface96c04cefcded01b9))
* **generate:** only mock boundaries the scenario's entry can reach ([#143](https://github.com/Landparty/mocky-mock/issues/143)) ([2fac1a1](https://github.com/Landparty/mocky-mock/commit/2fac1a17758742496fc9dc32eb008cab1b94878d))
* **generate:** pass a LINK server its commarea so the ABEND guard is not taken ([c7865cb](https://github.com/Landparty/mocky-mock/commit/c7865cb9ed8156b976c41f96ce0e2a52d5339ea0)), closes [#245](https://github.com/Landparty/mocky-mock/issues/245)
* **generate:** refuse to overwrite an existing .cut without --force ([6bc6a55](https://github.com/Landparty/mocky-mock/commit/6bc6a5508816def7f278c5a555f7adc50e2472be)), closes [#201](https://github.com/Landparty/mocky-mock/issues/201)
* **generate:** replicate a READ's AT END clause all or nothing ([25059f7](https://github.com/Landparty/mocky-mock/commit/25059f7703ff36aed899342a39c7d80f2685daa6)), closes [#217](https://github.com/Landparty/mocky-mock/issues/217)
* **generate:** replicate AT END SET &lt;88&gt; TO TRUE into READ mock exhaustion ([625eec0](https://github.com/Landparty/mocky-mock/commit/625eec0cdf627fd4a7cc3a77459afa0e3aa84e6b))
* **generate:** scaffold a subprogram through its USING parameters ([17d5fe2](https://github.com/Landparty/mocky-mock/commit/17d5fe2fdf7c54a221d2d3929f33188561baca56)), closes [#275](https://github.com/Landparty/mocky-mock/issues/275)
* **generate:** scaffold every boundary a paragraph reaches; wrapped USING headers ([6a11ce4](https://github.com/Landparty/mocky-mock/commit/6a11ce43d1114e725d41d1ac3765728e3748a0eb))
* **generate:** set a varying-length READ's DEPENDING ON item per row ([4c16518](https://github.com/Landparty/mocky-mock/commit/4c165188212ae099d6c7e11dc086a0850ff805a4)), closes [#214](https://github.com/Landparty/mocky-mock/issues/214)
* **generate:** surface the fixture bundle's unresolved warnings ([8a5cf07](https://github.com/Landparty/mocky-mock/commit/8a5cf073a6d96e5c1c01872ce7b49bb200501d4b)), closes [#331](https://github.com/Landparty/mocky-mock/issues/331)
* **generate:** treat a SORT's RELEASE/RETURN as expected placeholders ([488b961](https://github.com/Landparty/mocky-mock/commit/488b96177cb9d0e32c872fcea44f0dfb071fee1e)), closes [#262](https://github.com/Landparty/mocky-mock/issues/262)
* **generate:** use INITIALIZE as the ACCEPT placeholder body ([b2b8150](https://github.com/Landparty/mocky-mock/commit/b2b8150c0559bf769db120d55fd63dde00d6ecc5)), closes [#330](https://github.com/Landparty/mocky-mock/issues/330)
* **generate:** verify a READ outside any loop once, not once per generated row ([358db08](https://github.com/Landparty/mocky-mock/commit/358db08b9c3fdd6b78f34af49bb438c5950a3683))
* **generate:** write a recordable STUB EXPECT for a WRITE's record ([d18d29a](https://github.com/Landparty/mocky-mock/commit/d18d29aa3e5e7c310530f021c1b1ef394d4b9857)), closes [#255](https://github.com/Landparty/mocky-mock/issues/255)
* **generate:** write COBOL names, not the bundle's RECORD.FIELD ([#144](https://github.com/Landparty/mocky-mock/issues/144)) ([e00c821](https://github.com/Landparty/mocky-mock/commit/e00c821acfa10e3d7e9ff3490e959e66a93f62f1))
* **generate:** write only a SELECT/FETCH mock's INTO host variables ([dcb95d1](https://github.com/Landparty/mocky-mock/commit/dcb95d1db76663fbfcaba42d35ad3671366d4bed)), closes [#239](https://github.com/Landparty/mocky-mock/issues/239)
* **init:** record expectations when only the toolchain image is missing ([d2268f5](https://github.com/Landparty/mocky-mock/commit/d2268f56fd1ed50028a6ec3768eb13fc72c637ce))
* **journal:** read entries back split on "\n" only ([bcd6289](https://github.com/Landparty/mocky-mock/commit/bcd6289311efb60ba56c47d08cb3c515cc43108d)), closes [#283](https://github.com/Landparty/mocky-mock/issues/283)
* JSON report attribution, stubs in PROVIDER blocks, mock-body placeholders, stmt-delete on numbered sources ([2f01078](https://github.com/Landparty/mocky-mock/commit/2f0107873301a06c7b11343da1d5c1b0da81ceb6))
* **labels:** a label at the top of a test case covers the case; warn on labels that cover nothing ([#346](https://github.com/Landparty/mocky-mock/issues/346)) ([f9dc72c](https://github.com/Landparty/mocky-mock/commit/f9dc72cba060afbf475d7b4c92e107c1e7f96eb4))
* **linkage:** read LINKAGE SECTION header line from CobolSection.location ([6d52232](https://github.com/Landparty/mocky-mock/commit/6d522326da3714596535cfc23261df3e023818d2))
* **lint:** check one-line MOVE statements inside MOCK bodies ([3ea49d8](https://github.com/Landparty/mocky-mock/commit/3ea49d86e30b28840b7e4482e3663173a01355de)), closes [#243](https://github.com/Landparty/mocky-mock/issues/243)
* **lint:** check ROWS and TERMINAL field names and values ([ca10b36](https://github.com/Landparty/mocky-mock/commit/ca10b362d18e350b2695f9982baec97a9d4a1dfa)), closes [#299](https://github.com/Landparty/mocky-mock/issues/299)
* **lint:** know data names built through REPLACE pseudo-text ([99d1982](https://github.com/Landparty/mocky-mock/commit/99d19829ec275797198279665f67ca531a0964ce)), closes [#273](https://github.com/Landparty/mocky-mock/issues/273)
* **lint:** know only the UT- names this suite's driver declares ([9c60b6c](https://github.com/Landparty/mocky-mock/commit/9c60b6c601d878510669d095df5b0b149e989483)), closes [#296](https://github.com/Landparty/mocky-mock/issues/296)
* **lint:** refuse an EXPECT whose TRUE/FALSE form does not match the item's level ([5cf7bee](https://github.com/Landparty/mocky-mock/commit/5cf7beed7d9ea7a1bd42f655ead494b00db2d909)), closes [#307](https://github.com/Landparty/mocky-mock/issues/307)
* **lint:** warn when a case reaches an untestable omitted-argument test ([a86edb8](https://github.com/Landparty/mocky-mock/commit/a86edb8a311d1a80b847bb8468d7555636823e6c)), closes [#288](https://github.com/Landparty/mocky-mock/issues/288)
* **mock:** let a test pin ACCEPT FROM DATE/TIME, and never record the clock ([2b1a9f2](https://github.com/Landparty/mocky-mock/commit/2b1a9f20b92a16397aece633a87830c19c1af1cc)), closes [#240](https://github.com/Landparty/mocky-mock/issues/240)
* **mutate:** carry END-&lt;verb&gt; through the arithmetic verb swap ([b8e17e0](https://github.com/Landparty/mocky-mock/commit/b8e17e05fb3c5ee2245ca1933418d8b3359ba15c)), closes [#234](https://github.com/Landparty/mocky-mock/issues/234)
* **mutate:** hint at zero-start ADD/SUBTRACT survivors; document READ mock scope ([6f0f6a1](https://github.com/Landparty/mocky-mock/commit/6f0f6a15ba624c310af8169dc1e3137a7b6aee9a))
* **mutate:** hint at zero-start ADD/SUBTRACT survivors; document READ mock scope ([6a59bdd](https://github.com/Landparty/mocky-mock/commit/6a59bdd958e896337171bd751055b6b968a0f6b9))
* **mutate:** never mutate a line inside a multi-line EXEC block ([18b779e](https://github.com/Landparty/mocky-mock/commit/18b779e10d4a84c673e3a3594a2635bb9ddd6927)), closes [#202](https://github.com/Landparty/mocky-mock/issues/202)
* **mutate:** never score a mutant the Docker toolchain failed under ([#347](https://github.com/Landparty/mocky-mock/issues/347)) ([b591526](https://github.com/Landparty/mocky-mock/commit/b591526bc81f33b594923b74f81ec2fa133deff1))
* **mutate:** no stillborn deletion of a multi-receiver MOVE; show cobc's error ([fed8a41](https://github.com/Landparty/mocky-mock/commit/fed8a41ba3d911d62e8f2bbe975dd422765191a2))
* **mutate:** no zero-baseline hint for ADD/SUBTRACT that runs in a loop ([4d2b6d8](https://github.com/Landparty/mocky-mock/commit/4d2b6d8dc59c4796dd1618e78a99e47587c775a2)), closes [#203](https://github.com/Landparty/mocky-mock/issues/203)
* **mutate:** skip debugging lines unless the program is in debugging mode ([3d197a9](https://github.com/Landparty/mocky-mock/commit/3d197a913916b015fcfdd001f3c384f8e3c8e870))
* **mutate:** stop generating mutants that cannot compile ([6ef9fee](https://github.com/Landparty/mocky-mock/commit/6ef9fee462cebede685d064220021f36faac89f5))
* **mutate:** type the stillborn reason as a literal, not a narrowed str ([b193603](https://github.com/Landparty/mocky-mock/commit/b1936032803b61f6c6ad8c44a04fc221a8dca1da))
* **mutation:** don't call unasserted zero-baseline survivors untestable ([27b6373](https://github.com/Landparty/mocky-mock/commit/27b6373b8a67c4e3fe0c36810ac1e031c0e28ca5))
* **mutation:** map a mutant's line into the expanded AST for the loop check ([5a015a3](https://github.com/Landparty/mocky-mock/commit/5a015a39053b7f85e47fa23e570019c8abb96fc0)), closes [#342](https://github.com/Landparty/mocky-mock/issues/342)
* open bug-audit issues (WS reset, mutate, debugger, .cut parsing, lint) ([498dd28](https://github.com/Landparty/mocky-mock/commit/498dd282e47f58364fcee0a865354ac08b554ceb))
* per-suite reports, subprogram scaffolds, lint --case, and CLI support for extension fixes ([93ab185](https://github.com/Landparty/mocky-mock/commit/93ab18512b995da074f2ac0efe8f1910591b4484))
* PERFORM THRU range returns in reachability, UT-CAP- literal captures, name placeholders, coverage label ([7420624](https://github.com/Landparty/mocky-mock/commit/74206249f3414439fa04651d81d5f95b05986872))
* prevent recommending --scenarios branches when all arms are missed ([5ff55b6](https://github.com/Landparty/mocky-mock/commit/5ff55b607b598c447da2485c771ad3c56965cdbe))
* **record-expectations:** skip a STUB EXPECT written above the PERFORM ([a9fa5df](https://github.com/Landparty/mocky-mock/commit/a9fa5df074f7e4dcfab043d3d72c09a97e7edfed))
* recorded numeric expectations, REDEFINES reset, sentence periods in .cut ([cb93d35](https://github.com/Landparty/mocky-mock/commit/cb93d35daf5a9c87e3348cb2baa672c3d2de0df4))
* **record:** skip goldens whose bytes the run's output could not carry ([#146](https://github.com/Landparty/mocky-mock/issues/146)) ([b5d151a](https://github.com/Landparty/mocky-mock/commit/b5d151a1196e691238818f342d160546c0c0df11))
* **refusal:** accept a READ/RETURN ROWS mock whose AT END clause ends the loop ([a7beef2](https://github.com/Landparty/mocky-mock/commit/a7beef2c850b3bca972584921ab48e0019bdbf73)), closes [#341](https://github.com/Landparty/mocky-mock/issues/341)
* **refusal:** accept a REPLACE left in force to the end of the source ([44ca0c2](https://github.com/Landparty/mocky-mock/commit/44ca0c2b8322340035bd98cf9bcbec0d56ee6939)), closes [#272](https://github.com/Landparty/mocky-mock/issues/272)
* **refusal:** judge an EXEC SQL WHENEVER jump per case, not per program ([f1a37e0](https://github.com/Landparty/mocky-mock/commit/f1a37e0a5844de0ea26d60a848903ae150b901d9)), closes [#244](https://github.com/Landparty/mocky-mock/issues/244)
* **refusal:** refuse a mocked site whose clause bodies cannot be lifted ([ea6b817](https://github.com/Landparty/mocky-mock/commit/ea6b8170647bb4068f60b773caf7d67e83d0e288)), closes [#319](https://github.com/Landparty/mocky-mock/issues/319)
* **refusal:** refuse CAPTURE ARG of an OMITTED CALL argument ([3f49d31](https://github.com/Landparty/mocky-mock/commit/3f49d31e5da013ac6e281864a80c90c764fc94f8))
* **refusal:** refuse CAPTURE ARG of an OMITTED CALL argument ([d3212d3](https://github.com/Landparty/mocky-mock/commit/d3212d39b05796c7b6c878f8c893d0b51fbd997c))
* **refusal:** scope UNSUPPORTED_CICS_MACRO by reachability ([2df9002](https://github.com/Landparty/mocky-mock/commit/2df9002303946bbb098b62904c06b069f8b3722f))
* **refusal:** tolerate phantom "." paragraphs in goto-exit adjacency check ([c8124f7](https://github.com/Landparty/mocky-mock/commit/c8124f77fee8f4de41b0845fa051dc85fb545652))
* refuse out-of-order .cut statements; scaffold IMS DLITCBL programs ([#150](https://github.com/Landparty/mocky-mock/issues/150)) ([e569169](https://github.com/Landparty/mocky-mock/commit/e569169cdd34222e6263afe134c097f682a63f96))
* regenerate stale uv.lock pinning cobolparser to a July git SHA ([e305e1f](https://github.com/Landparty/mocky-mock/commit/e305e1f598fc289099e829a318d1ba2a621cba1b))
* **report:** attribute a PROVIDER template's assertions to each row ([ff7e05a](https://github.com/Landparty/mocky-mock/commit/ff7e05ab68a2094c6fa9b70c6963b5d34b202b77)), closes [#328](https://github.com/Landparty/mocky-mock/issues/328)
* **report:** count failed cases, not failed checks, in the console summary ([fda1e69](https://github.com/Landparty/mocky-mock/commit/fda1e69ce25b912e75c9bc0f55d617a92c5f2667)), closes [#235](https://github.com/Landparty/mocky-mock/issues/235)
* **report:** fail the run step when the suite never compiled ([388593f](https://github.com/Landparty/mocky-mock/commit/388593fe5dcfe8766f49fe6b4822fc57ce9fdb17)), closes [#260](https://github.com/Landparty/mocky-mock/issues/260)
* **report:** keep leading spaces of a failure's actual in the JSON report ([1e4c22f](https://github.com/Landparty/mocky-mock/commit/1e4c22fbcd3f60bb2d85991d4f70e702e6a5b6bb)), closes [#335](https://github.com/Landparty/mocky-mock/issues/335)
* **report:** let PERFORM &lt;section&gt; reach the section's paragraphs ([d25bf6f](https://github.com/Landparty/mocky-mock/commit/d25bf6f1d9f3338365563bf7e0d4e9b8a5864b41)), closes [#292](https://github.com/Landparty/mocky-mock/issues/292)
* **report:** list cases that never started in console and JUnit output ([#150](https://github.com/Landparty/mocky-mock/issues/150)) ([08a9fa6](https://github.com/Landparty/mocky-mock/commit/08a9fa6d641d5a51d1569444ae9c6fa52980feb8))
* **report:** match run results to same-named cases by .cut line ([d1fe868](https://github.com/Landparty/mocky-mock/commit/d1fe86828516d7b3ed2c05b1e034f094fd25f146)), closes [#304](https://github.com/Landparty/mocky-mock/issues/304)
* **report:** parse protocol markers that follow NO ADVANCING output ([#139](https://github.com/Landparty/mocky-mock/issues/139)) ([bd12509](https://github.com/Landparty/mocky-mock/commit/bd12509dda4a45a3bbcef818c321ea26cd96b4dc))
* **report:** record-expectations goldens that fail on the next run ([5c201dc](https://github.com/Landparty/mocky-mock/commit/5c201dc1bce4907178a09a513a3605a643ef4798)), closes [#194](https://github.com/Landparty/mocky-mock/issues/194)
* **report:** write one report per suite, named after the .cut ([#192](https://github.com/Landparty/mocky-mock/issues/192)) ([73e3aab](https://github.com/Landparty/mocky-mock/commit/73e3aababa6ae3c5df7b02c5219c97411ca36604))
* **reset:** reset USAGE INDEX items and PICTURE-less binary/float usages ([b8fb9d6](https://github.com/Landparty/mocky-mock/commit/b8fb9d600e53b06fe90749d605c748d9c690892c)), closes [#333](https://github.com/Landparty/mocky-mock/issues/333)
* **run:** give an unnamed PROCEDURE DIVISION main line its own paragraph ([d8aff2b](https://github.com/Landparty/mocky-mock/commit/d8aff2bf09720eef0d51d515e26d04ece5909ba2)), closes [#264](https://github.com/Landparty/mocky-mock/issues/264)
* **run:** keep a CRLF .cut CRLF when --record-expectations rewrites it ([1f2dee6](https://github.com/Landparty/mocky-mock/commit/1f2dee69c709097886b6d7789e6dd32c84a3f754)), closes [#199](https://github.com/Landparty/mocky-mock/issues/199)
* **run:** record a level-88 stub as TRUE/FALSE and an index-name as its occurrence ([63d24f9](https://github.com/Landparty/mocky-mock/commit/63d24f963f34cd430d6b1b94245161e526a58694)), closes [#237](https://github.com/Landparty/mocky-mock/issues/237)
* **run:** rejoin a FAIL/RECORD value split at an X'0A' byte ([702b0d6](https://github.com/Landparty/mocky-mock/commit/702b0d6632694dd6684b3e0e93e852df05603306)), closes [#285](https://github.com/Landparty/mocky-mock/issues/285)
* **run:** synthesize the DL/I interface block for programs that test DIBSTAT ([#145](https://github.com/Landparty/mocky-mock/issues/145)) ([13524d2](https://github.com/Landparty/mocky-mock/commit/13524d28016eac913429c9e6ca7b3b24a55bddb8))
* **runtime:** add -std=mvs so cobc compiles EJECT/SKIP1-3 sources ([ecc7dbe](https://github.com/Landparty/mocky-mock/commit/ecc7dbeacf4de9ac410e8c2a9d40fef114c0b416))
* **runtime:** find config/copy/extras at the root of a Windows GnuCOBOL tree ([e120331](https://github.com/Landparty/mocky-mock/commit/e120331c869a213880f463440656fd6668329319))
* **runtime:** resolve gcov and gdb on the native tree's PATH ([05266ec](https://github.com/Landparty/mocky-mock/commit/05266ec8fce2b57841575eecf07b7b6438687dd6))
* second bug-audit sweep, every remaining medium and low issue plus the late highs (87 issues) ([d3a983d](https://github.com/Landparty/mocky-mock/commit/d3a983dd76af90fbf5085162e092f1bd9095d111))
* **splicer,export:** hex-literal prefixes on line breaks, sentence period before inline comment, driver fields without WORKING-STORAGE, UT-CAP- sizing and reset ([7b29116](https://github.com/Landparty/mocky-mock/commit/7b291169882c7e27adadbf77d6a11da854d37238))
* **splicer:** byte-copy edited items in the BEFORE-ALL snapshot ([0d45f54](https://github.com/Landparty/mocky-mock/commit/0d45f54cf56d94a5187ba57162a4d0fc6bc1b61c)), closes [#224](https://github.com/Landparty/mocky-mock/issues/224)
* **splicer:** carry INDEXED BY indexes through the BEFORE-ALL snapshot ([9aafc43](https://github.com/Landparty/mocky-mock/commit/9aafc4390dc03bc4a1f536b30b5cd8b931bddb00)), closes [#280](https://github.com/Landparty/mocky-mock/issues/280)
* **splicer:** clear a VALUE-less FILLER when resetting its group ([71b2de4](https://github.com/Landparty/mocky-mock/commit/71b2de4eccfc1c5810214dcc0e2c0e46e08537b3)), closes [#278](https://github.com/Landparty/mocky-mock/issues/278)
* **splicer:** copy alphanumeric-edited values as bytes in reset, rows and captures ([baec76e](https://github.com/Landparty/mocky-mock/commit/baec76e5313453312e4438e629d439277dad55cc)), closes [#277](https://github.com/Landparty/mocky-mock/issues/277)
* **splicer:** default a mocked EXEC CICS command's RESP to NORMAL ([b6bae8c](https://github.com/Landparty/mocky-mock/commit/b6bae8cb3cb8123cbb7a0f9c300117e2b4747560)), closes [#320](https://github.com/Landparty/mocky-mock/issues/320)
* **splicer:** emit lifted clause bodies verbatim so they stay mapped ([fdd77c1](https://github.com/Landparty/mocky-mock/commit/fdd77c1ef7190e55cad156a610efb7697df03825)), closes [#332](https://github.com/Landparty/mocky-mock/issues/332)
* **splicer:** emulate EXEC SQL WHENEVER instead of mocking it ([9105bec](https://github.com/Landparty/mocky-mock/commit/9105bec189c005f9875f51d2c7e2e9d6f6a4eeb4)), closes [#195](https://github.com/Landparty/mocky-mock/issues/195)
* **splicer:** end the run after a mocked EXEC CICS RETURN/XCTL/ABEND ([8bef33e](https://github.com/Landparty/mocky-mock/commit/8bef33e4d29b63cbf36999ba01e4e0f5fb890c9f)), closes [#215](https://github.com/Landparty/mocky-mock/issues/215)
* **splicer:** exit the whole SECTION from a chain check in its first paragraph ([f097328](https://github.com/Landparty/mocky-mock/commit/f097328765ffe8f063c73a1d6cf7b842cd829271)), closes [#338](https://github.com/Landparty/mocky-mock/issues/338)
* **splicer:** give the synthesized SQLCA its SQLEXT group (136 bytes) ([010d9e0](https://github.com/Landparty/mocky-mock/commit/010d9e08454141573cbbfe8b9607200c045e4ae9)), closes [#271](https://github.com/Landparty/mocky-mock/issues/271)
* **splicer:** keep a STOP RUN/GOBACK RETURNING operand when neutralizing ([6850d87](https://github.com/Landparty/mocky-mock/commit/6850d87ed69351735af86315ecdbec9716051373)), closes [#219](https://github.com/Landparty/mocky-mock/issues/219)
* **splicer:** keep SET ADDRESS OF as a real rebind when the address is the program's own ([55490b4](https://github.com/Landparty/mocky-mock/commit/55490b4ad786eab5e11ba064d61ebe73808270dd)), closes [#226](https://github.com/Landparty/mocky-mock/issues/226)
* **splicer:** keep the implicit MOVE of a mocked READ … INTO / WRITE … FROM ([#149](https://github.com/Landparty/mocky-mock/issues/149)) ([d5b24c3](https://github.com/Landparty/mocky-mock/commit/d5b24c3c9c22593fc3c582f496341d4c3994f311))
* **splicer:** keep the ROWS cursor across hook steps; VERIFY via a baseline ([f7cc4fc](https://github.com/Landparty/mocky-mock/commit/f7cc4fcf737c934ebf156973af2e6ddc2f5c9bd0)), closes [#223](https://github.com/Landparty/mocky-mock/issues/223)
* **splicer:** leave FILLER out of an ODO counter's qualified name ([0d9a6c5](https://github.com/Landparty/mocky-mock/commit/0d9a6c50d1a5eb3f64a8bcaf05c014205f7761a3)), closes [#246](https://github.com/Landparty/mocky-mock/issues/246)
* **splicer:** let a MOCK SQL ROWS row set its own SQLCODE ([ba3320a](https://github.com/Landparty/mocky-mock/commit/ba3320aaf009222050b36ac9f1b96eab42f1a961))
* **splicer:** let a MOCK SQL ROWS row set its own SQLCODE ([394627c](https://github.com/Landparty/mocky-mock/commit/394627cec9b9d4be2403bac0b6053f266cd0257a))
* **splicer:** let a mocked NOHANDLE CICS terminator return control on failure ([517b51c](https://github.com/Landparty/mocky-mock/commit/517b51cc0a7a228dda6a687b60b9f979b6404ee1)), closes [#301](https://github.com/Landparty/mocky-mock/issues/301)
* **splicer:** make every tally name a pure function of (category, key) ([129cc95](https://github.com/Landparty/mocky-mock/commit/129cc9538ec2e9f0e55676e25fdd2d0593d74481)), closes [#314](https://github.com/Landparty/mocky-mock/issues/314)
* **splicer:** mocked WRITE/REWRITE set the file's FILE STATUS ([6000eee](https://github.com/Landparty/mocky-mock/commit/6000eeef7fc412ea7621590bdc5101ee0631e988)), closes [#221](https://github.com/Landparty/mocky-mock/issues/221)
* **splicer:** negate a combined EXPECT condition as a whole ([63e8f01](https://github.com/Landparty/mocky-mock/commit/63e8f0153763ecdc3f8f3f9618e9a7abdeecb8b9)), closes [#265](https://github.com/Landparty/mocky-mock/issues/265)
* **splicer:** never comment out a compiler-directing line after a spliced statement ([bdeb90e](https://github.com/Landparty/mocky-mock/commit/bdeb90eeca9098b53e1d03affa0d04329cb9ccae)), closes [#310](https://github.com/Landparty/mocky-mock/issues/310)
* **splicer:** never name an ambiguous top-level item bare in the reset or snapshot ([aba6505](https://github.com/Landparty/mocky-mock/commit/aba65052015073922572e2220f39987ce06bc190)), closes [#281](https://github.com/Landparty/mocky-mock/issues/281)
* **splicer:** place a nested chain PERFORM's early-exit check inside its branch ([95b85ac](https://github.com/Landparty/mocky-mock/commit/95b85ac3ce2b18d1f71e60da645e6be71b623f79)), closes [#337](https://github.com/Landparty/mocky-mock/issues/337)
* **splicer:** qualify an INDEXED BY name two tables declare ([df6e992](https://github.com/Landparty/mocky-mock/commit/df6e9927d93b2aec3da595e73cabd6cfb4992bcd)), closes [#249](https://github.com/Landparty/mocky-mock/issues/249)
* **splicer:** qualify group-child VALUE restores in the WS reset ([3150e9f](https://github.com/Landparty/mocky-mock/commit/3150e9f0af0cb94712519466e81e48636d0069e6)), closes [#220](https://github.com/Landparty/mocky-mock/issues/220)
* **splicer:** READ ... INTO copies like a real READ ([4d27274](https://github.com/Landparty/mocky-mock/commit/4d2727476ed04646109524fca720a4dbe72e811c))
* **splicer:** recognize a literal CALL argument next to a subscripted operand ([066906b](https://github.com/Landparty/mocky-mock/commit/066906b440f774a42a067954c49336484bdcffc0)), closes [#291](https://github.com/Landparty/mocky-mock/issues/291)
* **splicer:** repair two compile-blocking codegen bugs from the corpus ([69ce403](https://github.com/Landparty/mocky-mock/commit/69ce403b849d04ff77e0de21f356dd5026f141b4))
* **splicer:** report SQLSTATE from a MOCK SQL ... ROWS mock ([935ffae](https://github.com/Landparty/mocky-mock/commit/935ffaeeefb8b05c37e4ef4f2e44b171f2dadb7a)), closes [#313](https://github.com/Landparty/mocky-mock/issues/313)
* **splicer:** reset and snapshot the named items under a FILLER group ([f7ec230](https://github.com/Landparty/mocky-mock/commit/f7ec230c842861ae3628576f788a93fcdf7f9051)), closes [#247](https://github.com/Landparty/mocky-mock/issues/247)
* **splicer:** reset INDEXED BY indexes between cases; support EXPECT &lt;88&gt; TO BE TRUE ([5d112db](https://github.com/Landparty/mocky-mock/commit/5d112dba0e8b8d74d37622a224d78a8a0cd21326)), closes [#189](https://github.com/Landparty/mocky-mock/issues/189)
* **splicer:** reset LOCAL-STORAGE and FILE SECTION records between cases ([#147](https://github.com/Landparty/mocky-mock/issues/147)) ([69b0d32](https://github.com/Landparty/mocky-mock/commit/69b0d3235d0e35b26531485e5f690578e25c505c))
* **splicer:** reset OCCURS DEPENDING ON tables at their maximum size ([9bde545](https://github.com/Landparty/mocky-mock/commit/9bde545e9987f1ab11c7c95aaaf105b24842a6bb)), closes [#216](https://github.com/Landparty/mocky-mock/issues/216)
* **splicer:** restore FILLER VALUEs in the WORKING-STORAGE reset ([b45e2ca](https://github.com/Landparty/mocky-mock/commit/b45e2cade12c2505913b1efcfe05f7e9e1d6110f)), closes [#196](https://github.com/Landparty/mocky-mock/issues/196)
* **splicer:** restore numeric-edited and JUSTIFIED VALUEs byte-faithfully ([54e1ab6](https://github.com/Landparty/mocky-mock/commit/54e1ab6f3f7a55aa03806dc14e9f1c4fb0ff2d03)), closes [#218](https://github.com/Landparty/mocky-mock/issues/218)
* **splicer:** run a mocked statement's own clause bodies by its outcome ([a82ec38](https://github.com/Landparty/mocky-mock/commit/a82ec389280a730f0b28dafc5a3f62a4d98a2109)), closes [#209](https://github.com/Landparty/mocky-mock/issues/209)
* **splicer:** snapshot the synthesized EIB, DIB and SQLCA around BEFORE-ALL ([290ca2c](https://github.com/Landparty/mocky-mock/commit/290ca2c8555b40fca03b153fbb5ba13c599621fa)), closes [#225](https://github.com/Landparty/mocky-mock/issues/225)
* **splicer:** splice a nested READ/CALL bounded by its own END-xxx ([6689692](https://github.com/Landparty/mocky-mock/commit/66896922b1d1d9dfbf808497d46a27e00d971de0)), closes [#258](https://github.com/Landparty/mocky-mock/issues/258)
* **splicer:** splice a nested RETURN ... END-RETURN like a nested READ ([62f66cc](https://github.com/Landparty/mocky-mock/commit/62f66cc885cd0ab2df454a23726aa029517c6d98)), closes [#340](https://github.com/Landparty/mocky-mock/issues/340)
* **splicer:** splice TRUE/FALSE assigned to a level-88 as SET, not MOVE ([aca6d9f](https://github.com/Landparty/mocky-mock/commit/aca6d9f3bb34f669957d2e2235c58001b71d25bc)), closes [#251](https://github.com/Landparty/mocky-mock/issues/251)
* **splicer:** split long EXPECT/MOVE literals across driver lines ([3ccde53](https://github.com/Landparty/mocky-mock/commit/3ccde5350f28bb9e62d68d7bc6a55e8e803662d2))
* **splicer:** split long literals in hook MOVEs, ROWS and mock bodies ([7b4edfa](https://github.com/Landparty/mocky-mock/commit/7b4edfa8d94132830ad13f0a7e14d9200cade498)), closes [#322](https://github.com/Landparty/mocky-mock/issues/322)
* **splicer:** validate replace_columns' span against the line ([1a11c8b](https://github.com/Landparty/mocky-mock/commit/1a11c8bbce099362e458a0c87d42c71198eee9af))
* split COBOL source on record boundaries only, capture args across call sites, text-field expectations ([2ffc101](https://github.com/Landparty/mocky-mock/commit/2ffc101cd47a6d596fcbcdbd09c7ceb67501ff61))
* split source lines the way the installed cobolparser numbers them ([66f3c07](https://github.com/Landparty/mocky-mock/commit/66f3c0734da983bdb16a65a7f850c390d9c3fc23))
* stop SQLCODE leaking between calls and cases ([#148](https://github.com/Landparty/mocky-mock/issues/148)) ([f3df54a](https://github.com/Landparty/mocky-mock/commit/f3df54a74bc05f6dc5284a32315e0ea5b0d4e5a6))
* **suite-hooks:** own mocks under EACH hooks, early-exit flag, hint seeding ([f577c0f](https://github.com/Landparty/mocky-mock/commit/f577c0fd45871478b6d0c5c147558f0d8aced5ca))
* sync __version__ and plugin.json to 0.9.0; use release-please's generic updater ([80b699c](https://github.com/Landparty/mocky-mock/commit/80b699caa6c011b3ab865887053c103b2c39299f))
* sync mockymock.__version__ to 0.8.0 and pin release-please to the file ([2a58c6c](https://github.com/Landparty/mocky-mock/commit/2a58c6c9458debcf499d74c2b54b8087cee59af2))
* **trace:** keep procedure-copybook statements in the executed path ([3f1cc2b](https://github.com/Landparty/mocky-mock/commit/3f1cc2bea893665c7005ba21badf6613b86267a4)), closes [#242](https://github.com/Landparty/mocky-mock/issues/242)
* **trace:** scope run --trace to the selected case's own span ([f73c645](https://github.com/Landparty/mocky-mock/commit/f73c645ce00ea10e2ef8d4139de3d8556d75a107)), closes [#334](https://github.com/Landparty/mocky-mock/issues/334)
* write comma-decimal literals for DECIMAL-POINT IS COMMA programs ([1378402](https://github.com/Landparty/mocky-mock/commit/13784025d30bcca0a209a7fafb5344dbb1f0c599)), closes [#230](https://github.com/Landparty/mocky-mock/issues/230)


### Performance Improvements

* **analysis:** remove the quadratic scans from the static-check pass ([cc1f17e](https://github.com/Landparty/mocky-mock/commit/cc1f17e2d2dd5bdd24b1a0ba1353fff25fc25304))


### Documentation

* **cobol-test:** point the skill at the report's program analysis ([877e0b1](https://github.com/Landparty/mocky-mock/commit/877e0b16fb6a846037e652826e3214dcc5545441))
* correct the FieldSpec "mirrored" claim in the interface contract ([44adf27](https://github.com/Landparty/mocky-mock/commit/44adf2763da88506dbc37d7298666b543c1a6610))
* design plan for .cut editor completion, hover, and quick fixes ([5c3bd49](https://github.com/Landparty/mocky-mock/commit/5c3bd49aca78e0b2f6d92649ab9ab55700a6d5ff))
* design plans for a more approachable CLI/DSL onboarding path ([0ed1925](https://github.com/Landparty/mocky-mock/commit/0ed192502c5e8cc57fa94562c912f88ece215e82))
* eighth project audit -- four new findings, two of nine fixed ([1f5aa94](https://github.com/Landparty/mocky-mock/commit/1f5aa94806e2315cfe998e241779f8c46d2d6c22))
* **examples:** bring the real-world suites back to green ([#150](https://github.com/Landparty/mocky-mock/issues/150)) ([2d97d9e](https://github.com/Landparty/mocky-mock/commit/2d97d9ead6539dc42a365ef78fd096cb1739c467))
* fix OUT-boundary filter and overclaims in scenario-generation.md ([635fec3](https://github.com/Landparty/mocky-mock/commit/635fec32803b3ad7fe7bdcbc782f9d1ca40cccfe))
* **mutate:** say what _sequence_area_end actually returns ([e63320a](https://github.com/Landparty/mocky-mock/commit/e63320abdcfcd415ec7967087bb892c4e4940359))
* **okf:** audit bundle against current code ([b6dc9c3](https://github.com/Landparty/mocky-mock/commit/b6dc9c3306d6464391e1feac0b7b6cf70e49e474))
* **okf:** bring the knowledge bundle back in step with the tree ([764e50e](https://github.com/Landparty/mocky-mock/commit/764e50ec65b209a9e77e10272219e635a69c551c))
* **okf:** document CLI argument-resolution changes ([95ac29f](https://github.com/Landparty/mocky-mock/commit/95ac29f93a2ffcc9cffdfc2d5aaf6a2d0fd12ba5))
* **okf:** log bug hunt round 10 ([59afea8](https://github.com/Landparty/mocky-mock/commit/59afea8da527a23540ff3923c4307e6d14eade55))
* **okf:** log bug hunt round 11 ([4913e81](https://github.com/Landparty/mocky-mock/commit/4913e816b7871ab59c09db2f78ca9adac5cf4a6a))
* **okf:** log bug hunt round 12 ([cf70caa](https://github.com/Landparty/mocky-mock/commit/cf70caa5816b058af2499ab727a57cbedf516833))
* **okf:** log the 2026-10-16 bug-audit sweep ([a796c6d](https://github.com/Landparty/mocky-mock/commit/a796c6d55f1a4f8a53559058ec94e9ee3ee8e252))
* **okf:** log the second bug-audit sweep ([f6b1b40](https://github.com/Landparty/mocky-mock/commit/f6b1b40fec3f5c4d1f7c30c3ede31f4d64af9b09))
* **okf:** record the 2026-10-05 bug-hunt fixes ([#139](https://github.com/Landparty/mocky-mock/issues/139)-[#150](https://github.com/Landparty/mocky-mock/issues/150)) ([128f0b6](https://github.com/Landparty/mocky-mock/commit/128f0b64a4d4d50e3a199ec4d64291c575a48cf4))
* record cobol-parser's new copybook record-image formats ([b0d5235](https://github.com/Landparty/mocky-mock/commit/b0d5235359c8e1f895cebb9a57448f5d95b69130))
* record cobol-parser's new copybook record-image formats ([73f030a](https://github.com/Landparty/mocky-mock/commit/73f030a8d4a622567ae3440e07833ad39871bc85))
* record that generated scenarios never assert which branch they reach ([f45e228](https://github.com/Landparty/mocky-mock/commit/f45e2286a75cc87a5e77067318ebddaf95f97d3d))
* record the GnuCOBOL integration run for suite hooks ([b21b56f](https://github.com/Landparty/mocky-mock/commit/b21b56fc00bb3c140d66fab96908a97a00482a8c))
* seventh project audit — nine findings, none fixed ([b71aaa6](https://github.com/Landparty/mocky-mock/commit/b71aaa667b7fded19bb837a1f10262d280711fb6))
* **skill:** paragraph-first workflow + narration contract for the AI helper ([29363f7](https://github.com/Landparty/mocky-mock/commit/29363f74e4b7504676e51219359105e5ee76dbc5))
* **splicer:** say the reset clears the FD's longest record ([7d87d19](https://github.com/Landparty/mocky-mock/commit/7d87d198e64a552ddb634d6e94a756444a1ebc40))
* usability review of the first ten minutes with a COBOL program ([6413b24](https://github.com/Landparty/mocky-mock/commit/6413b24869c3867b5cacef1168a14c67708a289e))


### Miscellaneous Chores

* release 0.11.0 ([430786d](https://github.com/Landparty/mocky-mock/commit/430786d67dc4b6b11918d113d10b0726a5578a18))

## [0.11.0](https://github.com/Landparty/mocky-mock/compare/v0.10.2...v0.11.0) (2026-10-26)

### Added

- **Native GnuCOBOL backend (no Docker).** `MOCKYMOCK_GNUCOBOL_HOME` names a self-contained GnuCOBOL 3.2 tree and every command (`setup`, `doctor`, `run`, coverage, `mutate`, `debug`) compiles and runs with it on the host instead of in the `mockymock-cobc` container; `MOCKYMOCK_TOOLCHAIN=auto|docker|native` picks the backend explicitly (`auto`, the default, means native when the home is set). Verified on Linux and on Windows with the MinGW build the Chocolatey `gnucobol` package installs; the VS Code extension bundles a tree and sets both variables. Docker stays the default, and the only backend with the container's hardening. See `.okf/runtime.md`, "Native toolchain".

- **`MOCK CALL "X" ROWS ( ... ) TERMINAL ( ... )` -- one response per call.** A plain `MOCK CALL` answers every call of its key the same way, so a program calling one routine for several purposes (IMS `CBLTDLI` as priming GHN, DLET and loop GHN; `MQGET` loops; a DB2 access module) could only be driven end to end down its empty-input path. `ROWS` now works on `MOCK CALL` (static and dynamic), `MOCK MQ` and `MOCK DLI`, with the same grammar `READ` already has: row N answers that key's Nth call within the test case (counted across every call site), and `TERMINAL` answers every call after the last row. `TERMINAL` is required for these categories, since a CALL has no implicit end-of-data value and the last answer would otherwise repeat until `run --timeout` kills the loop. A `MOCK CALL` without `ROWS` splices exactly as before. `examples/real-world/ACCTPRG` gains two whole-program cases that run real purge-loop iterations.

### Changed

- **`UNSUPPORTED_NESTED_PROGRAM`**: a multi-unit compilation unit (nested or stacked `PROGRAM-ID`s, or an object-oriented `CLASS-ID` with its FACTORY/OBJECT/METHOD-ID units, which cobol-parser now parses) is refused under its own code. It used to be refused as `PARSE_WARNING` -- "the AST is missing content" -- which was wrong: cobol-parser parses every unit into `contained_programs`; what is missing is mockymock's support, since the splicer and the reachability BFS only see the outermost unit, so a contained unit's boundaries would go unmocked. The message now says that.
- **DECLARATIVES detection reads cobol-parser's modelled flag first.** Since cobol-parser's 2026-09-15 release every section between `DECLARATIVES.` and `END DECLARATIVES.` carries `CobolSection.is_declarative` (metadata `declarative`) and the two marker lines no longer leave a stray paragraph named `DECLARATIVES` behind -- the artifact `_check_unsupported_control_flow` used as its primary signal. That flag is now checked first; the stray paragraph and the `USE` statement fallback stay for an older pin, so `UNSUPPORTED_DECLARATIVES` holds on every cobol-parser version.
- **cobol-parser now expands `EXEC SQL INCLUDE` itself** (its 2026-09-15 release; `CopyStatementLexer(sql_include=True)`), so the DCLGEN members mockymock's own `splicer/sqlca.py` resolved one level deep become real WORKING-STORAGE items in the AST too: `custprog/CUSTPROG.cbl`'s `(SQL, FETCH)` boundary is no longer mockymock-only, and a member that itself says `EXEC SQL INCLUDE` is inlined rather than refused as nested. Both tests probe the installed cobol-parser for the capability and keep their old expectation on an older pin.
- **`tests/fixtures/enterprise/` + `tests/unit/test_enterprise_corpus.py`**: one representative program per IBM Enterprise COBOL program type (a copy of cobol-parser's `tests/samples/enterprise/`; keep the two identical), with the outcome of `mockymock generate` pinned per program -- scaffolds a `.cut`, scaffolds nothing (no mockable boundary: pure computation, XML/JSON, INVOKE), or refused under exactly one code (`UNSUPPORTED_CICS_MACRO` for `DFHRESP`/`DFHVALUE`, `UNSUPPORTED_LINKAGE_LAYOUT` for a default entry with its own `PROCEDURE DIVISION USING` -- the translated CICS form, an IMS MPP, a DB2 stored procedure --, `UNSUPPORTED_DECLARATIVES`, `UNSUPPORTED_NESTED_PROGRAM`). A program type silently changing sides is now a test failure. The matrix is `cobol-parser/docs/enterprise-program-types.md`.

- **`mockymock analyze gen-data` can now emit a copybook's real record bytes**, via `--format record` (packed/binary/zoned bytes a COBOL program would actually read) or `--format hex` (the same image annotated with each field's offset, length, PICTURE and USAGE — the form that survives being opened in an editor). No mockymock code changed: `analyze` is an unguarded `REMAINDER` passthrough into cobol-parser's CLI, so every new `gen-data` flag — `--charset ascii|ebcdic`, `--endian`, `--record-separator` — is available as soon as cobol-parser has it. Worth knowing because the VS Code extension's "Generate Data from Copybook" action builds exactly this invocation; surfacing the format there is an extension-side change. mockymock's own mocking never needed it — the splicer emits `MOVE <literal> TO <field>` and lets GnuCOBOL pack the value, so `COMP-3`/`COMP-5` boundaries already worked.
- `examples/fixtures/FIXTUREDEMO.bundle.json` re-copied from cobol-parser. Its `FieldSpec` entries gained four **additive** keys (`storage_size` — the item's real byte width, as opposed to `size`, which counts PICTURE character positions; plus `sign_clause`, `synchronized`, `occurs_depending_on`). `bundle_version` stays `1` and `dsl/fixture_bundle.py` ignores unknown keys, so the loader is unchanged.

### Added

- **Universal `cobol.yml` project config.** One YAML file at a project's root, read by `mockymock`, `cobol-parser` and the COBOL Analyzer VS Code extension, instead of configuring the same copybook directories three times in three places. Its `project:` section holds what every tool shares (`copybook_path`, `seed`); its `mockymock:` section holds this CLI's own (`test_root`, `ai_mode`) and overrides `project:`. An existing `mockymock.toml` / `[tool.mockymock]` keeps working exactly as before and now layers **over** the universal file key by key, each found by its own upward walk — so a `cobol.yml` at a repo root and a `mockymock.toml` in a subproject both apply, and a `mockymock.toml` that sets one key no longer has to restate the rest. `mockymock doctor` reports every file that contributed, in the order they apply. Reading the file needs cobol-parser >= 1.10; the dependency floor is deliberately unchanged, so only a project that actually writes a `cobol.yml` is asked to upgrade, by an error saying so. `mockymock skills mode --set` refuses to rewrite a `cobol.yml` and prints the two lines to paste instead. Design: `docs/2026-09-16-universal-yaml-config-design.md`.

- **`mockymock generate` now scaffolds `CAPTURE ARG <n> INTO ...` for every mockable CALL argument, and mockymock declares the storage.** Asserting on what a mocked `CALL` actually received is usually the most interesting assertion in a test, but the `CAPTURE ARG` target had to be an existing data item of a compatible type -- so finding or adding one was a manual step before every capture, and `generate` never emitted one (explicitly out of scope in the original argument-capture design). A target named `UT-CAP-...` now means "declare this for me": `splicer.captures` synthesizes a WORKING-STORAGE item mirroring the argument's own PICTURE/USAGE (a DISPLAY-only group becomes one `PIC X(<byte length>)` field, exactly what a group MOVE copies) plus a reset line between test cases, threaded through all four splice pipelines. The reserved prefix keeps it from being a footgun -- a mistyped real data name never starts with `UT-CAP-`. Fail-closed elsewhere: a new `UNRESOLVED_CAPTURE_TARGET` refusal covers an argument that names different items at different matching call sites, a layout that cannot be mirrored (a table, a PICTURE-less COMP-1/POINTER item, a group holding non-DISPLAY data), and a name the program already declares. A target without the prefix behaves exactly as before. `generate` also emits one `*> STUB EXPECT <target>` comment per capture, which `run --record-expectations` promotes to a real `EXPECT` from an actual run.
- `mockymock run --coverage-fail-under PERCENT` -- exits 1 when the ORIGINAL program's line coverage falls below the given percentage, the `run` counterpart of `mutate --fail-under`. Implies `--coverage`. Coverage previously could not be CI-gated at all even though mutation score could. Gated on the original program's number rather than the instrumented copy's (that one moves whenever mockymock's own injected line count changes, which says nothing about the program under test), folded into the command's final exit-code decision so `--trace` output still prints, and a failed `gcov` pass FAILS the gate -- "no number" must never read as "good enough".
- `refusal` code `UNMOCKABLE_ACCEPT_SOURCE` -- a `MOCK ACCEPT` aimed at an `ACCEPT <target> FROM DATE/TIME/DAY/COMMAND-LINE/...` now refuses with its own message saying that ACCEPT variant is not mockable at all (it reads a system register, never the console, so `mock_surface` deliberately creates no boundary site for it). It used to fall through to `UNMATCHED_MOCK: ... does not match any boundary site reachable from '<paragraph>'`, which reads as a call-graph reachability bug and sent authors off verifying reachability by hand for a problem that was never about reachability. `MockSurface.non_interactive_accepts` records these detected-and-deliberately-unmockable ACCEPTs for the message; they are still never spliced and never listed as unsupported boundaries.

- **`mockymock mutate` got its two big cost levers** (`docs/2026-07-29-mutation-testing-design.md`'s deferred items 1 and 3). Neither changes a verdict; both remove or spread work. **A coverage gate, on by default**: the baseline is compiled with GnuCOBOL's `--coverage` and its gcov output remapped onto the ORIGINAL source, so any mutant sitting on a line the whole suite provably never executes is reported `survived` from that evidence alone -- no splice, compile or run of its own. That is exact rather than heuristic: a line no test case reaches cannot change what any test case observes. A line *absent* from the remap (driver insertions, boundary replacements, continuation merges -- the cases `map_coverage_to_original` deliberately drops) is unknown, never "uncovered", and is always built. A `--coverage` build is a different compile and a slower binary than the one `run` performs, so a baseline that fails *at the compile step* or times out is re-run plain before it is believed -- while a genuinely red suite or a refusal-gate stop is not, since gcov instrumentation changes neither (the new `SuiteRun.phase`, "checks"/"compile"/"run", is what tells those apart, and is also the hook a future stillborn-vs-refused split needs). A gcov pass that produces nothing appends a `mockymock mutate:` note and the run builds everything. Gated survivors are scored exactly like built ones; they carry `ran: false` and `totals.not_compiled` in `--json-report` and print as `uncovered` rather than `SURVIVED`, so a verdict reached from coverage never reads as a mutant that was built and beat the suite. `--no-coverage-gate` builds everything. **And `--jobs N` / `-j N`** (default 1): the per-mutant pipeline spread across N worker *processes* -- processes, not threads, because the dominant Docker-free cost is `run_static_checks`, which is CPU-bound pure Python. Measured on a synthetic 3,610-line program on 4 cores: 1.93x at `--jobs 2`, 3.90x at `--jobs 4` (that program's static-check cost alone is ~23 minutes serial, before a single `cobc` runs). Results are consumed in submission order, so the report, the live progress stream and the notes union stay byte-identical to a serial run whatever order the workers finish in, and the source is handed to each worker once through the pool initializer rather than pickled per task. The default is 1 deliberately: the ceiling is not the core count but the shared `mockymock-cobc` container's `--memory 1g`, which every concurrent `cobc` draws from at once -- an OOM-killed compile would be recorded as a `stillborn`, a wrong verdict, quietly. **Neither lever has been exercised against a real Docker daemon** (none available where this was built); the coverage/parallel logic is covered by `tests/unit/test_mutation_speed.py` against a stubbed pipeline, and the parallel scaling number above was measured on the Python half only.
- **CICS implicit-linkage support**: a program referencing CICS EIB fields (`EIBCALEN`, `EIBAID`, `EIBTIME`, `EIBTRMID`, `EIBDATE`, ...) from ordinary COBOL outside any `EXEC CICS` block -- a real CICS translator inserts `DFHEIBLK`'s LINKAGE SECTION layout ahead of `cobc` ever seeing the source, so these names would otherwise fail compilation as undeclared -- now gets a synthesized `01 DFHEIBLK.` WORKING-STORAGE group with the standard IBM EIB layout, reset between test cases (`INITIALIZE DFHEIBLK`), and addressable from `.cut` `MOCK`/`EXPECT`/setup-move directives like any other field (`analysis.cics_eib`/`splicer.cics_eib`, wired into `run`/`debug`/`export`/`mutate`/`generate`). Also generalizes the existing IMS ENTRY/LINKAGE neutralization (`analysis.linkage.linkage_plan`) to LINKAGE SECTIONs with zero `ENTRY` statements -- the idiomatic CICS `LINKAGE SECTION. 01 DFHCOMMAREA. ...` / `PROCEDURE DIVISION.` (no `ENTRY`) shape is now real, addressable WORKING-STORAGE too, per the IMS design's own empirical finding that the storage is unbound regardless of `ENTRY`'s presence. Two new fail-closed refusals for what neither mechanism can safely handle: `UNSUPPORTED_CICS_MACRO` (`DFHRESP(...)`/`DFHVALUE(...)` macro calls, which only a real CICS translator can expand) and `UNSUPPORTED_CICS_DFHCOMMAREA` (`DFHCOMMAREA` referenced but never declared anywhere -- unknowable size). **Not yet verified against real GnuCOBOL** -- no working Docker daemon when this was built; see `docs/2026-08-27-cics-eib-linkage-support-design.md`'s "No corpus evidence" section for the required follow-up.
- `.cut` DSL: `EXPECT` negation and comparison operators — `EXPECT <name> [NOT] TO BE [GREATER THAN|LESS THAN [OR EQUAL TO]] <value>`. Each phrase normalizes at parse time to a canonical COBOL relation operator on `ExpectDirective.operator` (`=`, `NOT =`, `>`, `<`, `>=`, `<=` and their negations); plain `TO BE` stays exact equality, so every existing `.cut` file parses and compiles byte-identically. The generated failure check compiles the operator's negation (`TO BE GREATER THAN` emits `IF <name> NOT > <value>`); the FAIL line and the `--json-report` `expected` field carry the operator (`expected WS-X > 5, got 004`; the bare-value report shape is unchanged for plain equality). A dangling comparison phrase (`TO BE GREATER 5`, `... OR EQUAL 5`) is a line-numbered `CutParseError` instead of a cobc compile error in generated code.

- `.cut` DSL: `MOCK SORT <sd-name>` / `MOCK MERGE <sd-name>` (and matching `VERIFY`) — a plain-file-form `SORT ... USING ... GIVING ...` / `MERGE ... USING ... GIVING ...` (no INPUT/OUTPUT PROCEDURE) is now a mockable boundary, keyed by its own SD file name, spliced the same way as any other file-op verb. `MOCK RELEASE <record>` / `MOCK RETURN <sd-name>` (the latter also gaining the `ROWS ( ... ) TERMINAL ( ... )` sugar previously READ-only) — a pure `INPUT PROCEDURE ... OUTPUT PROCEDURE ...` SORT (no USING/GIVING at all) is left real/unspliced, with its RELEASE/RETURN statements independently mockable instead; the reachability gate now models a SORT/MERGE's INPUT/OUTPUT PROCEDURE as an implicit PERFORM edge so a RELEASE/RETURN reachable only through one is never invisible to the fail-closed refusal gate. `mockymock generate` scaffolds all four automatically. A SORT/MERGE mixing a USING/GIVING file with a procedure clause on the other side stays refused fail-closed with `UNSUPPORTED_SORT_MERGE` — mocking that shape would either skip the procedure's own logic or touch a physical file mockymock has no mechanism to seed. See `docs/2026-08-17-sort-merge-using-giving-mocking-design.md`.
- `mockymock fixtures <program> [--scenarios happy|branches|all] [--seed N] [--rows N] [--copybook-path DIR]...` — new subcommand: prints a cobolparser `FixtureBundle` (scenarios, seeded mock data, expectations) as JSON on stdout, for editor integrations. No Docker dependency; stdout is JSON only, all diagnostics go to stderr.
- `mockymock generate --with-data --rows N` — seeds the self-generating fixture bundle's row count (`--rows 0` is honored, not treated as falsy). Rejected with a stderr error and exit 1 when combined with `--fixtures`, whose row count is already baked into the checked-in bundle.
- `mockymock generate --placeholder CATEGORY:KEY` (repeatable; valid with either `--with-data` or `--fixtures`) — downgrades a matched fixture's mock body to its ordinary non-data placeholder while keeping it mocked; a malformed value (no `:`) exits 1, an unmatched pair warns on stderr. A downgraded loop-bearing boundary (a multi-row `READ`, a multi-row `SQL ... ROWS` cursor fetch) keeps real loop-termination semantics instead of silently hanging, and its tier-1 `VERIFY ... WAS CALLED n TIMES` is recomputed to match the downgraded body's actual call count (or demoted to a `*>` comment when that count isn't knowable by construction).
- `.cut` DSL: `ROWS` now applies to `MOCK READ <file> ROWS` (previously `MOCK SQL "..." ROWS` only), with an optional READ-only `TERMINAL ( FIELD = value, ... )` group for the rows-exhausted branch. Hand-authoring grammar only — the bundle-driven `generate --with-data`/`--fixtures` scaffold does not emit it.
- `refusal.find_goto_exit_plans` — automatically splices a `GO TO` into a provably no-op paragraph (one bare `EXIT.` statement) into `EXIT PARAGRAPH` at its own call site, letting a `STOP RUN`/`GOBACK` chain that was only blocked by that exact GO-TO-as-early-exit idiom qualify for terminator neutralization too. Only applies when the exit-only paragraph immediately follows the enclosing (top-level) paragraph in source order; SECTION-scoped enclosing paragraphs are not supported. **Not yet verified against real GnuCOBOL** — see `docs/2026-08-17-goto-exit-paragraph-simplification-design.md`'s Status note; the Docker-required integration fixture that would confirm it has not been run.

### Changed

- **`mockymock export` fits a literal-less overflow too, and its refusal names the real source.** Two follow-ups to the literal-continuation work landed in #101. First, `fit_within_columns` gained a third pass (`_break_at_whitespace`) for the one shape the first two cannot fit: a line with no literal at all (`MOVE WS-A-LONG-SOURCE-NAME TO WS-A-LONG-TARGET-NAME`), which pass 2 could only report as "holds no single quoted literal to split". A COBOL statement may span as many fixed-format lines as it needs -- only a *literal* broken across the boundary needs the column-7 `-` -- so that line needs no continuation machinery at all, just a break at a space with the remainder starting in Area B. Only a single word too long for Area B (61 characters) still refuses. Second, that refusal now names where the line came from (`SourceAttribution`): mockymock's own generated reset for a specific item, the `.cut` file and line, the `.cbl` file and line, or explicitly neither. The message used to assert "this typically comes from a `.cut` file's MOCK body text" whatever the real source was, sending readers to the wrong file whenever the offending text was mockymock's own generated code -- which no `.cut` edit could shorten. Matching is exact stripped-text lookup, so an attribution is a fact rather than an inference.

- **`mockymock run --coverage`'s console report now leads with the ORIGINAL `.cbl`'s own coverage.** There have always been two coverage numbers and, until now, the prominent one was the less useful one: the stdout line reported the *instrumented sandbox copy* (inflated by mockymock's injected dispatch/driver lines), while the meaningful original-file figure existed only inside `--coverage-json`. The headline percentage and the listed uncovered lines are now the original program's, by their original line numbers; the instrumented number still appears, once, on a labelled line saying why it is higher. `--coverage-json`'s `original` block gained a `percentage` key to match (additive -- a v1 consumer is unaffected).
- **`mockymock mutate` now reports WHY each stillborn mutant was stillborn.** Stillborn mutants are excluded from the mutation score entirely, so a bare count made them a black box: a line whose every mutant failed to compile looked identical to a line with no mutants at all, and a genuine gap the mutation engine could never probe hid behind a clean-looking score. `SuiteRun.phase` already knew the answer and was dropped when the `MutantResult` was built; it is now carried through as `stillborn_reason`, and the console report groups stillborns as `checks` (a mockymock static gate rejected the mutated program before any compiler ran -- often an equivalent mutant) vs `compile` (GnuCOBOL rejected it -- that line was never probed), listing each mutant under its reason. `--json-report` gained `stillbornByReason` totals and a per-mutant `stillbornReason`. The classification is never re-derived from the raw compiler/gate `detail` text.

- **`UNSUPPORTED_CICS_MACRO` is now reachability-scoped for `run`/`lint`/`export`/`debug`.** A `DFHRESP(...)`/`DFHVALUE(...)` call used to refuse the whole file the moment the text appeared anywhere in it -- on a real 16.9k-line CICS program, one such call in a screen-handling paragraph nothing under test performs blocked every test case in the file, with no `.cut` change able to work around it. It now travels the same held-back path `PARSE_WARNING` and `UNRESOLVED_COPYBOOK` already do (`check_cics_eib_layout_scoped`): refused only when some selected test case can execute the paragraph holding the call, otherwise waived with a transparency note. The macro is scopable because it describes *code that evaluates it*, not storage layout -- which is why `UNSUPPORTED_CICS_DFHCOMMAREA`, a missing declaration, stays whole-program unconditionally. A waived call is rewritten in place to `-1`, space-padded to the identical width so no line or column moves, since `cobc` has no CICS translator and could not compile the unexpanded macro even in dead code (the same reasoning as commenting out a waived unresolved `COPY`). Anything the classification cannot pin down -- a DATA DIVISION occurrence, a call continued across lines, an argument that is not a single COBOL word -- stays a whole-program refusal, fail closed; `generate`/`fixtures` (no test cases to scope by) keep the unconditional entry point. **The rewritten source has not been compiled against real GnuCOBOL** -- no working Docker daemon when this was built.
- **The static-check pass (`mockymock lint`/`run`) is now linear in program size instead of quadratic.** Three scans were the cause and all three are pure speedups -- `lint` output is byte-identical before and after, on runs producing thousands of refusals: `ScopeMap` queries were full scans of the boundary list (two of them copying the whole list first) with one query per boundary site, `collect_scope_map` re-scanned the EXEC-block range list per lexed token, and `_falls_through` was re-evaluated for every paragraph on every GO TO target's fall-through walk (4.4M calls on a 53k-line program in the shared-exit-label shape, where nothing on the chain provably diverts so each walk runs to end of program). Also collapsed `cics_eib_plan`'s 29 separate whole-text regex searches into one alternation pass. Measured on a 53k-line CICS-shaped program: 14.2s -> 5.5s.
- `refusal.check_test_case` gained a second `UNRESOLVED_FILE_STATUS_TARGET` trigger: a `MOCK READ ... ROWS` mock with neither its own `TERMINAL` group nor a declared `FILE STATUS` field on that file now refuses fail-closed instead of generating a read loop with no way to terminate.
- `splicer/injector.build_rows_block` generalized from a SQL-only function that hardcoded SQLCODE 0/100 to `build_rows_block(tally_name, rows, *, row_suffix_moves, exhausted_moves)`, with the SQLCODE literals moved to their SQL call site in `build_site_dispatch` and a new READ call site alongside it.
- **`cobol-parser` is now consumed as a normal pinned PyPI dependency (`cobol-parser>=1.7.7,<2`), not a vendored git-SHA pin.** `cobol-parser` publishes closed-source wheels to PyPI, so CI no longer checks out and builds the sibling repo from source; the editable sibling install and cross-repo checkout steps are gone from `requirements-dev.txt`/`ci.yml`.

### Fixed

- **`UNSUPPORTED_DECLARATIVES` no longer depends solely on one coincidental cobolparser parsing artifact.** The refusal's only signal was a stray paragraph literally named `DECLARATIVES` that cobolparser's parsing happens to leave behind for a `DECLARATIVES ... END DECLARATIVES` block -- a documented, coincidental artifact, not a modeled flag. GH issue #106 reported a real IMS DL/I program (`DECLARATIVES` + `USE FOR DEBUGGING ON ALL PROCEDURES`) whose splice/compile report showed no refusal at all, most likely because that artifact was lost to error-recovery resynchronizing after unrelated dropped content elsewhere in a much larger file -- the exact failure mode already documented for ordinary paragraph labels. `_check_unsupported_control_flow` now also refuses on a bare `UseStatement` node anywhere in PROCEDURE DIVISION when no named-`DECLARATIVES` paragraph is found: `USE` is legal nowhere else in COBOL, so its presence alone independently proves a `DECLARATIVES` section exists.
- **`mockymock generate --with-data` now surfaces cobol-parser's self-verification verdict.** A generated scenario's name is a claim about which branch its data reaches, and nothing in the generated `.cut` said whether that claim held -- confirming it meant running `mockymock run --trace` on every case. cobol-parser now verifies each scenario against its own generated data and records the result in the bundle; an `unverified` verdict renders as a `*> UNVERIFIED:` comment above the affected TESTCASE, naming each field whose generated values do not satisfy the branch and each enclosing condition that was never pinned. Verified scenarios get no note, and a bundle produced before the key existed is read as "no verdict recorded" rather than as unverified.
- **A scaffolded `MOCK READ`'s `WHEN OTHER` arm now carries the program's own `AT END` imperative instead of a `TODO` comment.** The splicer replaces the WHOLE `READ` statement, deleting its `AT END` clause with it -- so a generated mock that moves only the FILE STATUS field never runs the program's own end-of-data handling, and a `PERFORM ... UNTIL <eof-flag>` loop keyed on it spins until the executor timeout. A `TODO` left in place is therefore not a visible gap but a silent 30-second hang with no diagnosis. The AST-driven replication (a literal-sourced `MOVE`, a constant-valued `SET`) is unchanged and still preferred; when it comes up empty, `_lifted_at_end_lines` now lifts the clause's own source text verbatim -- a slice of the program, exactly the text the splice is about to delete, so it covers identifier-sourced MOVEs, `ADD`, `IF`, `PERFORM` and everything else a real clause holds rather than only the shapes an AST walk knows. `AT END` is located positionally with words scanned outside quoted literals (a `DISPLAY "AT END OF FILE"` is never mistaken for it) and cut at the first of `NOT AT END` / `END-READ` / `INVALID KEY` / a sentence-terminating period. Lifted lines carry a `*>` comment naming the source line. The `TODO` remains as the fallback when the clause cannot be located.
- **`mockymock generate --with-data` no longer silently drops the bundle's boundary-level stub expectations.** Every `WRITE:` (and any other OUT-direction) tier-3 stub in the bundle was discarded on the reasoning that the same boundary's `call_count` VERIFY already covered it -- but an OUT-direction boundary has no such VERIFY, so the analysis knew something the generated `.cut` never said. They now render as `*> STUB EXPECT <CATEGORY> <KEY> -- <note>` comments (inert, so they cannot break the generated file), and are dropped only when this same TESTCASE genuinely emits a live `VERIFY ... WAS CALLED` for that boundary. The two-token boundary form does not match the `--record-expectations` scanner's data-name grammar, so it is left alone there rather than mistaken for a data item.

- **`mockymock mutate` generated stillborn mutants on traditional 80-column source (four distinct causes).** Measured over a 542-file corpus (the vendored NIST CCVS85 suite, the shamrice examples, and this repo's own fixtures), **2,165 of 17,689 generated mutants -- 12.2% -- were defective**: each wasted a full splice/compile/run cycle and inflated the `stillborn` count that is supposed to measure operator precision. (1) **Column overflow**: mockymock normalizes source by slicing columns 8-72, so `ADD..TO -> SUBTRACT..FROM` (seven characters longer) pushed its own tail off the end of 671 lines. (2) **Identification-area drag**: the inverse swap is seven characters *shorter*, and carrying the rest of the line along with the edit slid columns 73-80 leftwards into the program text on 1,775 lines -- `NC1014.2` becoming code. Running every mutant through the same `normalize_fixed_format` the pipeline feeds `cobc` puts a verified floor under both: 1,580 of them (8.9% of the whole population) compiled something other than what their own report line described -- 546 with identification text leaked into the program, 1,209 with the statement's tail cut off; afterwards, none do. Both causes are now one `_rewrite_code` helper that rewrites strictly within columns 1-72 and re-pins the identification area at column 73, reclaiming the columns a longer verb needs from interior whitespace runs (never from the indent that decides Area A vs Area B, never from inside a literal -- which still recovers 287 of the 671 overflowing sites) and refusing the mutant outright when the line cannot give them up. (3) **`\b` word boundaries on the arithmetic verbs**: the same bug audit finding F8 fixed for `_EXCLUDED_VERBS`/`_SCOPE_TOKENS` was still live in `_ADD_TO`/`_SUBTRACT_FROM`/`_MULTIPLY_BY`/`_DIVIDE_INTO`/`_MOVE_INT`, so `\bADD\b` matched inside `GRP-FOR-ADD-CORR-R` and rewrote an ordinary `MOVE` to `MOVE GRP-FOR-SUBTRACT-CORR-R FROM ...` (102 occurrences); they now use the shared `_cobol_word()` helper like every other pattern in the module. (4) **`stmt-delete` on the head of a multi-line statement**: replacing `COMPUTE WS-AVG =` with `CONTINUE` strands its own second half, and replacing an `ADD` whose `END-ADD` is two lines down strands the scope terminator (135 occurrences). Deletion now requires the statement to provably end on its own line -- a trailing period, or a next code line that opens something new -- and refuses a line trailing off in a preposition. Also: fixed-format continuation lines (indicator `-`) are no longer treated as mutable code, and `PROCEDURE DIVISION` state is reset at `END PROGRAM`/a following `IDENTIFICATION DIVISION` so a second program's DATA DIVISION is not mutated as if it were procedural. Net effect on the same corpus: 621 sites are no longer offered as mutants at all, every remaining mutant compiles the program its own report line describes, and the Docker-gated integration fixture's pinned mutant population is unchanged.
- **`mockymock export` no longer refuses a line just because a quoted literal makes it overflow column 72 -- it continues the literal.** Reported from a real export of a 52-boundary program: after 50 refusals were worked around by shortening `.cut` text, two remained that no `.cut` edit could reach. They came from the program's own `DEBUT-WORKING-STORAGE` / `FIN-WORKING-STORAGE` storage-dump marker fields (declared, never referenced -- standard practice in IBM shops), whose `VALUE` clauses `splicer/reset.py` re-serializes into `UT-RESET-WORKING-STORAGE` as single-line `MOVE`s 85 columns wide. Unconditional -- it happens even with `--case` restricting the run to one `TESTCASE` -- and with no flag to skip it, so the only remedy was editing production COBOL to shorten a banner string. Now `mainframe_export.wrap_long_literal_lines` splits the literal across fixed-format continuation lines (`-` in the indicator area, the literal re-opened at column 12) leaving the statement and the literal's content byte-for-byte unchanged, and the new `fit_within_columns` sequences the two passes: generated `DISPLAY`s first (their byte-identical-stdout equivalence is what the `__MOCKYMOCK__` protocol rides on), then literal continuation over the residue, reporting only lines *neither* pass can fit. Every continued line is filled to exactly column 72 -- not cosmetic: a continued line's trailing blanks through column 72 are part of the open literal, so a short one silently pads the value with spaces (both directions verified against real GnuCOBOL 4.0 in fixed format, and pinned by `tests/integration/test_export_literal_continuation.py`). The same change fixes a second refusal with the same cause: a literal the *original* source already continued, which cobolparser's `normalize_fixed_format` collapses onto one long line. Still fail-closed for what cannot be continued -- no literal on the line, two literals (ambiguous), non-literal text that alone overflows, or a `CBL`/`PROCESS` directive. See `docs/2026-09-04-export-literal-continuation-design.md`.
- **`SET ADDRESS OF <item>` on a LINKAGE item folded into WORKING-STORAGE no longer fails the compile.** The ENTRY/LINKAGE neutralization exists to give a program's LINKAGE items real, addressable storage -- and that is exactly what makes rebinding their address illegal afterwards: GnuCOBOL rejects `SET ADDRESS OF X TO <ptr>` with `cannot change address of 'X', which is not BASED or a LINKAGE item`. On the IMS DL/I PSB-scheduling idiom (a `7000-SCHEDULE-PSB` paragraph doing this once per PCB/DIB mask) that is ~20 hard compile errors per program, all introduced by the fold itself. Marking the folded items `BASED` instead would restore the statement's legality by taking their storage away again -- the precise unbound-memory SIGSEGV the fold was built to prevent -- so the statement gives, not the storage: `splicer.linkage.redirect_address_of` rewrites each **receiving-side** `ADDRESS OF <folded item>` to a scratch `UT-ADDR-SINK USAGE POINTER`, space-padded to the identical width via `stub_writer.replace_columns` so no line and no column any AST location indexes into moves. The rebind is discarded, the `SET` keeps executing, and a sibling statement sharing the line is untouched. Value-side occurrences (`SET <ptr> TO ADDRESS OF <folded item>`) are deliberately left alone -- taking the address of a WORKING-STORAGE item is legal and stays correct after the fold. Detection is textual because cobolparser's `SetStatement` drops the target-side `ADDRESS OF` entirely (`SET ADDRESS OF X TO Y` and `SET X TO Y` both arrive as `targets=["X"]`), and anything it cannot classify or express as a single-line span -- an `ADDRESS OF` continued onto the next line, one with no `SET` on its own line -- is a new fail-closed `UNSUPPORTED_LINKAGE_ADDRESSING` refusal rather than a guess. Verified end to end against real GnuCOBOL 4.0: the rewritten program compiles, runs, and passes its test case; the un-rewritten one does not compile.
- **A VALUE clause holding a double quote generated an unterminated literal in `UT-RESET-WORKING-STORAGE`.** CICS's `DFHAID` copybook legitimately declares `DFHTRIG PIC X VALUE IS '"'` -- content: one quote character. cobolparser (through 1.8.0) re-quotes a decoded literal without doubling an embedded quote, so it arrived as three quote characters and the reset paragraph emitted `MOVE """ TO DFHTRIG`, desynchronizing `cobc`'s tokenizer for the rest of the program -- surfacing as a bogus `invalid symbol '%'` error two lines further on, nowhere near the cause. Fixed upstream (cobol-parser `_literals.quote_literal`), but the dependency floor is `cobol-parser>=1.7.7`, so `splicer.reset.cobol_literal` normalizes the clause here too: a run of quote characters is grown to the next even length, which repairs the malformed shape and is idempotent against the fixed parser. Verified against real GnuCOBOL 4.0.
- **`compile_source` couldn't compile real z/OS mainframe sources containing `EJECT`/`SKIP1`/`SKIP2`/`SKIP3` compiler-directing statements.** GnuCOBOL's default dialect doesn't implement those IBM listing directives at all, even though cobol-parser itself already treats them as no-ops (see its `EjectStatement`/`SkipStatement` AST nodes). Added `-std=mvs` to the `cobc` invocation in `docker_toolchain.py`, which GnuCOBOL does implement them under.
- **`find_goto_exit_plans`: transitive fallthrough chain among top-level GO-TO-exit paragraphs declined all at once (HIGH).** The function evaluated every exit-only-paragraph candidate against `_go_to_targets`/`_go_to_fallthrough_targets` computed ONCE, up front, from the raw whole-program GO TO set — so back-to-back validation paragraphs each with their own adjacent bare-EXIT label (`2211-VALIDER-MNT`/`2211-EXIT`, immediately followed by `2212-...`/`2212-EXIT`, and so on, chaining through ~20 paragraphs on a real program) were all declined together: neutralizing the first would have removed its exit label from `_go_to_targets`, un-marking the second as a fallthrough hazard and unblocking it in turn, but the single static pass never got to see that. Now iterates to a fixpoint — each round narrows `_go_to_targets` by every target confirmed in an earlier round, re-derives `_go_to_fallthrough_targets`, and re-evaluates every still-undecided candidate — until a round confirms nothing new, resolving the whole chain instead of declining it wholesale. Pinned by `tests/unit/test_goto_exit.py::test_find_goto_exit_plans_resolves_a_transitive_fallthrough_chain`.
- **Reachability gate: section-scoped GO TO fall-through false cascade (HIGH).** The "GO TO <own-exit-label>" idiom several validation paragraphs in the SAME SECTION each use as an early bailout to a shared, section-scoped exit label could not be neutralized by `find_goto_exit_plans` (its adjacency check only ever matches ONE of the several enclosing paragraphs, so its all-or-nothing rule declines the whole target), leaving `_reachable_paragraphs`/`union_executed_paragraphs` to model the un-neutralized exit label's fall-through as cascading past the section boundary into every paragraph physically after it — demanding mocks for boundaries a `PERFORM <section-name>`-entered test can never reach, hundreds of spurious `UNMOCKED_*` refusals on a real program. New `_fallthrough_safe_sections`/`_walk_fallthrough_from` recognize a SECTION provably entered only via `PERFORM <section-name>` and stop the fall-through walk at the section's own last paragraph instead of cascading past it — gate-only, `find_goto_exit_plans`/`find_terminator_plans` splice exactly as before. Pinned by `tests/unit/test_reachability_goto_exit_section_scoped.py`.
- **`linkage_plan`'s LINKAGE SECTION header line derivation.** `header_line` used to be computed as "one line before the first LINKAGE SECTION data item" — a workaround for a since-fixed cobolparser bug where a `DATA DIVISION` section reported its parent division's location instead of its own header token. On a real IMS PCB-mask LINKAGE SECTION (a boilerplate comment block before the first `01`-level item, as in `ACCTPRG`/`DEPTIMSM`-style programs), that derivation landed inside the comment block instead of on the header — measured to drift 12-14 lines on real-world programs — and `check_linkage_layout` correctly refused (`UNSUPPORTED_LINKAGE_LAYOUT`, "could not locate the LINKAGE SECTION header line") rather than comment out the wrong line, but that meant the ENTRY/LINKAGE neutralization feature never engaged for those programs. Now reads the LINKAGE SECTION's own `CobolSection.location` directly, which cobolparser has reported correctly since its "Section/Paragraph Location Tracking" fix. Pinned by `tests/unit/test_linkage.py`'s new comment-block regression cases.
- **Reachability gate: GO TO fall-through closure (HIGH).** `_reachable_paragraphs` stopped at a `GO TO` target, so a paragraph entered by falling off that target's end — ordinary sequential execution, which `union_executed_paragraphs`, the terminator guard, and cobolparser's `ProgramFlowAnalyzer` all already modeled — was invisible to the per-case mock gates: a `CALL`/file-op/`ACCEPT` there passed `lint`/`run` unmocked (exit 0) and executed for real at runtime. The BFS now closes over the fall-through hazard to a fixpoint via `_falls_through`, failing closed (`UNRESOLVED_FLOW_TARGET`) when paragraph source order is unverifiable or a GO TO target cannot be anchored in it. Pinned by `tests/unit/test_refusal_goto_fallthrough.py`.
- `mockymock generate --with-data --placeholder CATEGORY:KEY` (#47): downgrading a loop-driving boundary (a multi-row `READ`, a multi-row `SQL ... ROWS` cursor fetch) no longer leaves a DIFFERENT boundary's `VERIFY ... WAS CALLED n TIMES` pinned to the bundle's original, now-stale count when that other boundary is only reached from inside the same loop (e.g. a `CALL` made once per row) -- its VERIFY is demoted to a `*>` comment too, on the same "declared in the same paragraph as the downgraded boundary" heuristic.
- **`find_goto_exit_plans`: adjacency check broke on a phantom `"."` paragraph between enclosing and target.** cobolparser inserts an empty-artifact paragraph literally named `"."` for a bare `.` line sitting on its own between a paragraph's last statement and the next paragraph's header; `immediately_follows` required `target_idx == enclosing_idx + 1` exactly, so a phantom sitting between an otherwise-adjacent `GO TO`'s enclosing paragraph and its exit-only target broke the adjacency check and cascaded into declining that target and every paragraph transitively chained after it. `immediately_follows` now accepts any run of only phantom `"."` paragraphs strictly between the two, the same tolerance `_expand_thru_range` already applies elsewhere. Pinned by `tests/unit/test_goto_exit.py::test_find_goto_exit_plans_tolerates_a_phantom_paragraph_before_the_target`.

## [0.10.2](https://github.com/Landparty/mocky-mock/compare/v0.10.1...v0.10.2) (2026-10-16)


### Bug Fixes

* **analysis:** keep the qualifiers of a FILE STATUS IS field ([59065cc](https://github.com/Landparty/mocky-mock/commit/59065cc7e0a570cca503051e57731709e3abbc96)), closes [#266](https://github.com/Landparty/mocky-mock/issues/266)
* **analysis:** key an ACCEPT site on its target's data-name ([ecaa9f3](https://github.com/Landparty/mocky-mock/commit/ecaa9f3664b862a48a2d49780df99f04925a01e2)), closes [#311](https://github.com/Landparty/mocky-mock/issues/311)
* **analysis:** neutralize EXIT PROGRAM like GOBACK in the program under test ([8c52170](https://github.com/Landparty/mocky-mock/commit/8c52170f200503501e0ed8ebb7fa884c7ace3435)), closes [#212](https://github.com/Landparty/mocky-mock/issues/212)
* **analysis:** refuse a case that reaches a paragraph name defined in two SECTIONs ([f92a779](https://github.com/Landparty/mocky-mock/commit/f92a77932ad5ba2ee8ad3b57b1b55de9d6dc7b54)), closes [#284](https://github.com/Landparty/mocky-mock/issues/284)
* **analysis:** refuse MOCK SECTION when its paragraphs are referenced qualified ([83c9d93](https://github.com/Landparty/mocky-mock/commit/83c9d9399608c69ca51eeb1616ac61d9b0a819ee)), closes [#293](https://github.com/Landparty/mocky-mock/issues/293)
* **analysis:** refuse terminators a .cut PERFORM THRU range would run past ([6d2ea90](https://github.com/Landparty/mocky-mock/commit/6d2ea90e610bbb108032370ecef108d4461b9f7d)), closes [#211](https://github.com/Landparty/mocky-mock/issues/211)
* **analysis:** skip the GO TO exit rewrite when a PERFORM lacks the THRU ([82f7ce5](https://github.com/Landparty/mocky-mock/commit/82f7ce53a67f2f5b397d2f21a30c09044445e189)), closes [#213](https://github.com/Landparty/mocky-mock/issues/213)
* **analysis:** stop the terminator planner's GO TO fall-through walk at a safe section's end ([3efbeb1](https://github.com/Landparty/mocky-mock/commit/3efbeb1692f479d58a61536792681459f60b2a6f)), closes [#259](https://github.com/Landparty/mocky-mock/issues/259)
* **analysis:** treat a PROCEDURE DIVISION EXEC SQL DECLARE as a declaration ([3f491ae](https://github.com/Landparty/mocky-mock/commit/3f491aeb73f6ede1f2002f53e6881e94e1442d6d)), closes [#267](https://github.com/Landparty/mocky-mock/issues/267)
* **checks:** compile D lines as code under WITH DEBUGGING MODE ([eb7a75b](https://github.com/Landparty/mocky-mock/commit/eb7a75b50119a42051b39460c24358e087f0caf4)), closes [#274](https://github.com/Landparty/mocky-mock/issues/274)
* **checks:** judge shared-mock reach over the whole suite, not the selection ([8c682d5](https://github.com/Landparty/mocky-mock/commit/8c682d54e52987b6f7e028838122ac5200a73547)), closes [#250](https://github.com/Landparty/mocky-mock/issues/250)
* **checks:** refuse .cut data-names the program does not declare ([4c7025e](https://github.com/Landparty/mocky-mock/commit/4c7025e457993827fac82f6ae17212fc246ebfcb)), closes [#204](https://github.com/Landparty/mocky-mock/issues/204)
* **checks:** refuse free-format COBOL instead of column-chopping it ([cc2f8ef](https://github.com/Landparty/mocky-mock/commit/cc2f8effc02dc78c38978a5d7e3f5b7993dc3e9c)), closes [#210](https://github.com/Landparty/mocky-mock/issues/210)
* **checks:** synthesize DFHEIBLK/DLIDIB when only the .cut names a field ([d2ba9ad](https://github.com/Landparty/mocky-mock/commit/d2ba9ad691d280b1583a0f23b9bc4786c0676377)), closes [#269](https://github.com/Landparty/mocky-mock/issues/269)
* **cics:** emulate EXEC CICS HANDLE/IGNORE CONDITION instead of mocking it ([0805938](https://github.com/Landparty/mocky-mock/commit/0805938ef6db93454a66e2d55fd9dd38086c5cfd)), closes [#268](https://github.com/Landparty/mocky-mock/issues/268)
* **clause-bodies:** refuse unterminated nested phrases, not phrase words ([3422ed5](https://github.com/Landparty/mocky-mock/commit/3422ed5e4241a21f722941ee1a0e125e77630d80)), closes [#326](https://github.com/Landparty/mocky-mock/issues/326)
* **clause-bodies:** skip inline *&gt; comments when scanning clause bodies ([d4bd42c](https://github.com/Landparty/mocky-mock/commit/d4bd42c80326c4e66ded09f22e3588e248754101)), closes [#327](https://github.com/Landparty/mocky-mock/issues/327)
* **cli:** collect --boundaries resolves copybooks like lint and run ([792e57f](https://github.com/Landparty/mocky-mock/commit/792e57f1ca3449925b57219d97e3db8d26b2e6fc)), closes [#200](https://github.com/Landparty/mocky-mock/issues/200)
* **cli:** create a report file's parent directory, report write failures on stderr ([06747e8](https://github.com/Landparty/mocky-mock/commit/06747e84436f603aa985fe5ce4adab886aec3e53)), closes [#257](https://github.com/Landparty/mocky-mock/issues/257)
* **cli:** fail run/lint over a directory on a broken PROGRAM line ([0b6085a](https://github.com/Landparty/mocky-mock/commit/0b6085aa2afa51c349fa9e4a938c4a10217767af)), closes [#303](https://github.com/Landparty/mocky-mock/issues/303)
* **cli:** find suites in a tests folder outside the project root ([226abc1](https://github.com/Landparty/mocky-mock/commit/226abc1d7fb1ce78f30217a4be9be6bb9927d0e1)), closes [#294](https://github.com/Landparty/mocky-mock/issues/294)
* **cli:** find WORKING-STORAGE/PROCEDURE headers with any whitespace between words ([e4947af](https://github.com/Landparty/mocky-mock/commit/e4947af338bfaa2b681fb53b429538f708a25e2d)), closes [#305](https://github.com/Landparty/mocky-mock/issues/305)
* **cli:** keep collect --json errors machine-readable ([95790c9](https://github.com/Landparty/mocky-mock/commit/95790c96907b536c181c91630ddbca2d22116eb5)), closes [#309](https://github.com/Landparty/mocky-mock/issues/309)
* **cli:** pair a dotted program with the suite generate wrote for it ([3db37f8](https://github.com/Landparty/mocky-mock/commit/3db37f8e5d5114cb43ecc97355bcef55124ddc01)), closes [#289](https://github.com/Landparty/mocky-mock/issues/289)
* **cli:** refuse --timeout below 1 second ([c590901](https://github.com/Landparty/mocky-mock/commit/c5909010f806bbe68e6773372677a4a33560666b)), closes [#306](https://github.com/Landparty/mocky-mock/issues/306)
* **cli:** report refusal lines in the .cbl the user has open ([213b6e4](https://github.com/Landparty/mocky-mock/commit/213b6e4a281d59c691d4b59f1319d08070d21220)), closes [#241](https://github.com/Landparty/mocky-mock/issues/241)
* **cli:** skip suites with no selected case when running a project with --tag/--case ([2abe68b](https://github.com/Landparty/mocky-mock/commit/2abe68bc68364c98572e36981b088c5ceed3cf31)), closes [#254](https://github.com/Landparty/mocky-mock/issues/254)
* **cli:** validate generate/init/suites --name as one plain word ([624c4ea](https://github.com/Landparty/mocky-mock/commit/624c4eac29453c8726c2a64068f497d28d5c31d9)), closes [#336](https://github.com/Landparty/mocky-mock/issues/336)
* **coverage:** count a replaced boundary or GOBACK as the line it was ([e7a0d9f](https://github.com/Landparty/mocky-mock/commit/e7a0d9f8fed06834000ac9035bf7c9aecf88cc1b)), closes [#297](https://github.com/Landparty/mocky-mock/issues/297)
* **debug:** decode numeric-edited, COMP-1 and COMP-2 fields ([e24805c](https://github.com/Landparty/mocky-mock/commit/e24805c3522d81daa602ba92fcb965b09f23b5ff)), closes [#207](https://github.com/Landparty/mocky-mock/issues/207)
* **debug:** decode P-scaled numeric items to the value they hold ([d85743b](https://github.com/Landparty/mocky-mock/commit/d85743b70f934e34df12f9d946731fdccb92d07b)), closes [#295](https://github.com/Landparty/mocky-mock/issues/295)
* **debug:** name call-stack paragraphs in original-file lines ([6fe6958](https://github.com/Landparty/mocky-mock/commit/6fe695851d76e7615a34dcbb7cf70ce9c2504ac3)), closes [#256](https://github.com/Landparty/mocky-mock/issues/256)
* **debug:** show an unreadable item instead of failing Variables ([460fcec](https://github.com/Landparty/mocky-mock/commit/460fcecc4aa0f3e0d202c4b2ecc383e01f9c30ed)), closes [#318](https://github.com/Landparty/mocky-mock/issues/318)
* **deps:** allow cobol-parser 3.x and lock to 3.0.0 ([7df54d1](https://github.com/Landparty/mocky-mock/commit/7df54d1a960f87403f0f7aaac9ea2501238fc7ed))
* **deps:** allow cobol-parser 3.x and lock to 3.0.0 ([5daf46d](https://github.com/Landparty/mocky-mock/commit/5daf46d366d1e21472e98376f99bdeb4550b30d1))
* **driver:** cap the UT-TESTSUITE- paragraph name at 30 characters ([95d4197](https://github.com/Landparty/mocky-mock/commit/95d4197e1bc5706709174b6736fdbb73ad6f0fa3)), closes [#279](https://github.com/Landparty/mocky-mock/issues/279)
* **driver:** guard a negated EXPECT with an AND/OR tail on the un-negated condition ([5437711](https://github.com/Landparty/mocky-mock/commit/5437711290957af40a7df78d35c00a1389e418c4)), closes [#339](https://github.com/Landparty/mocky-mock/issues/339)
* **dsl:** accept a .cut file saved with a UTF-8 BOM ([ed64adf](https://github.com/Landparty/mocky-mock/commit/ed64adf06513a186be903e3d446fcfc0cdcfed73)), closes [#198](https://github.com/Landparty/mocky-mock/issues/198)
* **dsl:** accept OF/IN-qualified data-names in MOVE, EXPECT, CAPTURE and stubs ([28a82fd](https://github.com/Landparty/mocky-mock/commit/28a82fdb3c03a8ec89fe6a86003c15fdf504ce80)), closes [#252](https://github.com/Landparty/mocky-mock/issues/252)
* **dsl:** accept TAGS after USING PROVIDER on a TESTCASE line ([127fced](https://github.com/Landparty/mocky-mock/commit/127fcedd1832e3f396e12a47e38805769506209f)), closes [#329](https://github.com/Landparty/mocky-mock/issues/329)
* **dsl:** refuse a MOCK body that PERFORMs, GOes TO or terminates ([9c0a3b7](https://github.com/Landparty/mocky-mock/commit/9c0a3b7eafe4d613e60df78c2c25f12f97282ed4)), closes [#287](https://github.com/Landparty/mocky-mock/issues/287)
* **dsl:** refuse a MOVE value ending in a sentence period ([53372bc](https://github.com/Landparty/mocky-mock/commit/53372bcf6fbf4e029ba4a7018d1bf38ba20fb7b7)), closes [#197](https://github.com/Landparty/mocky-mock/issues/197)
* **dsl:** refuse an empty TESTCASE name ([77342cd](https://github.com/Landparty/mocky-mock/commit/77342cdb50c0510735c5feb81f9103891e4b7cf9)), closes [#308](https://github.com/Landparty/mocky-mock/issues/308)
* **dsl:** refuse an unterminated quoted literal in a .cut value ([3d9cbd1](https://github.com/Landparty/mocky-mock/commit/3d9cbd1ea37fb3fbed744875e88eab1fccda8ecc)), closes [#270](https://github.com/Landparty/mocky-mock/issues/270)
* **dsl:** refuse PROVIDER placeholders in hook steps and hook MOCK bodies ([c476a21](https://github.com/Landparty/mocky-mock/commit/c476a2103f47b6105ed00b246624d9be77aeadd3)), closes [#227](https://github.com/Landparty/mocky-mock/issues/227)
* **dsl:** sequence MOCK ACCEPT and end a loop waiting on its sentinel ([647a0ad](https://github.com/Landparty/mocky-mock/commit/647a0ad7767b5137dae90d4c291c58b0b8d0df43)), closes [#263](https://github.com/Landparty/mocky-mock/issues/263)
* **dsl:** strip trailing *&gt; comments from parsed .cut lines ([c11f4bb](https://github.com/Landparty/mocky-mock/commit/c11f4bb713e3618fcc885db0795cef8d4386028d)), closes [#236](https://github.com/Landparty/mocky-mock/issues/236)
* **export:** fit column 72 in UTF-8 bytes, not characters ([e16a12e](https://github.com/Landparty/mocky-mock/commit/e16a12e58aeaee83a641d07ca3a603bf33ec214b)), closes [#298](https://github.com/Landparty/mocky-mock/issues/298)
* **export:** keep the CBL/PROCESS card first with ID DIVISION ([0cca970](https://github.com/Landparty/mocky-mock/commit/0cca970cbab81f50155ecb6d67f1472b7d901c27)), closes [#276](https://github.com/Landparty/mocky-mock/issues/276)
* **export:** keep the IBM-legal redirect instead of BASED rebinds ([5918f73](https://github.com/Landparty/mocky-mock/commit/5918f736d47feed55186274c89a9c9d68b7f0dec)), closes [#321](https://github.com/Landparty/mocky-mock/issues/321)
* **export:** tell the clause-body lift about the restored sequence area ([549553f](https://github.com/Landparty/mocky-mock/commit/549553f8cdeb67f807b007921f9b5fbdff3a17ad)), closes [#325](https://github.com/Landparty/mocky-mock/issues/325)
* **flow-mocks:** refuse a MOCK PARAGRAPH inside a SORT/XML procedure THRU range ([9d447eb](https://github.com/Landparty/mocky-mock/commit/9d447eba1db3cbeb1ea137525d8329f2566829f6)), closes [#261](https://github.com/Landparty/mocky-mock/issues/261)
* **generate:** --fill exits 1 on an unmocked hook boundary it cannot fill ([43ae2f9](https://github.com/Landparty/mocky-mock/commit/43ae2f9689d8d92d25438808f7e7218de71ee7a3)), closes [#208](https://github.com/Landparty/mocky-mock/issues/208)
* **generate:** answer a DL/I CALL with a blank PCB status ([67eb4e6](https://github.com/Landparty/mocky-mock/commit/67eb4e661f4eb30d55ea3c48c8264d680b56f450)), closes [#317](https://github.com/Landparty/mocky-mock/issues/317)
* **generate:** answer CICS RESP and RESP2 with NORMAL on the happy path ([4c3e9b0](https://github.com/Landparty/mocky-mock/commit/4c3e9b0ae230d90f7dd780b1757d09470c7dd9f6)), closes [#253](https://github.com/Landparty/mocky-mock/issues/253)
* **generate:** answer MQCC_OK / MQRC_NONE in generated MQ mocks ([4e52ff4](https://github.com/Landparty/mocky-mock/commit/4e52ff4a5c76af3d020790b5bbec67c630cbdb83)), closes [#205](https://github.com/Landparty/mocky-mock/issues/205)
* **generate:** cast the program for analyze_file_status_fields instead of a type: ignore ([0356811](https://github.com/Landparty/mocky-mock/commit/0356811b5b799696c6c9c056f0b7eea9dd2ac30e))
* **generate:** demote call counts for sites inside loops or PERFORMed twice ([62444f7](https://github.com/Landparty/mocky-mock/commit/62444f7a48199d2d169b59d06d8c861104dcb673)), closes [#290](https://github.com/Landparty/mocky-mock/issues/290)
* **generate:** don't call a program-supplied CALL a key mismatch ([bee590e](https://github.com/Landparty/mocky-mock/commit/bee590e06294d15bf1d0b249171568fee8a5d57d)), closes [#300](https://github.com/Landparty/mocky-mock/issues/300)
* **generate:** don't write a loop's control item from a CALL mock ([e0ab8da](https://github.com/Landparty/mocky-mock/commit/e0ab8da9c62e1d6f3e8bda9f00a472883cf99e88)), closes [#286](https://github.com/Landparty/mocky-mock/issues/286)
* **generate:** end a CICS browse loop guarded on its own RESP ([ceed9fe](https://github.com/Landparty/mocky-mock/commit/ceed9feefb91465a1a61815f7bf51ca6302e7742)), closes [#316](https://github.com/Landparty/mocky-mock/issues/316)
* **generate:** end a looped MQGET whose guard flag is set on its reply ([f651ac7](https://github.com/Landparty/mocky-mock/commit/f651ac7ea89cdf530a0135a3575b6464fcb6fb9c)), closes [#188](https://github.com/Landparty/mocky-mock/issues/188)
* **generate:** end a placeholder READ/RETURN mock's AT END loop ([48b4ca4](https://github.com/Landparty/mocky-mock/commit/48b4ca4bf9084767cef8c98e13051415be1f6b3a)), closes [#302](https://github.com/Landparty/mocky-mock/issues/302)
* **generate:** end an EXEC DLI get loop primed by a GN before it ([c6f7120](https://github.com/Landparty/mocky-mock/commit/c6f7120d2d4c1144ae1f740703c2b08dc14eb1a4)), closes [#315](https://github.com/Landparty/mocky-mock/issues/315)
* **generate:** enter a section-structured program at its main SECTION ([7abb4ad](https://github.com/Landparty/mocky-mock/commit/7abb4ad09877862076bc975fcf27f2ffe1d18346)), closes [#238](https://github.com/Landparty/mocky-mock/issues/238)
* **generate:** fail when the scaffold's own cases are refused ([517699d](https://github.com/Landparty/mocky-mock/commit/517699d9e1ad7040871628df104a4044f23cd322)), closes [#231](https://github.com/Landparty/mocky-mock/issues/231)
* **generate:** give prefix-nested EXEC sites one MOCK key ([c03f3e2](https://github.com/Landparty/mocky-mock/commit/c03f3e20e692c863f18d968bbba8dc6dd3db8c09)), closes [#248](https://github.com/Landparty/mocky-mock/issues/248)
* **generate:** key a multi-file OPEN/CLOSE so one MOCK covers its sibling sites ([fb9dd6e](https://github.com/Landparty/mocky-mock/commit/fb9dd6e0ef4ce3566d44097d6108c2e60982a49c)), closes [#312](https://github.com/Landparty/mocky-mock/issues/312)
* **generate:** leave a CICS command's input operands out of its mock ([1e08394](https://github.com/Landparty/mocky-mock/commit/1e08394a3ba47464bc503a147b096cb182ed1afd)), closes [#222](https://github.com/Landparty/mocky-mock/issues/222)
* **generate:** let [#188](https://github.com/Landparty/mocky-mock/issues/188)'s one-hop reply rule end MQGET drain loops ([3c34642](https://github.com/Landparty/mocky-mock/commit/3c3464269b1a9fc2c7d5ec0ccecf3f2ef7dec56c))
* **generate:** pass a LINK server its commarea so the ABEND guard is not taken ([c7865cb](https://github.com/Landparty/mocky-mock/commit/c7865cb9ed8156b976c41f96ce0e2a52d5339ea0)), closes [#245](https://github.com/Landparty/mocky-mock/issues/245)
* **generate:** refuse to overwrite an existing .cut without --force ([6bc6a55](https://github.com/Landparty/mocky-mock/commit/6bc6a5508816def7f278c5a555f7adc50e2472be)), closes [#201](https://github.com/Landparty/mocky-mock/issues/201)
* **generate:** replicate a READ's AT END clause all or nothing ([25059f7](https://github.com/Landparty/mocky-mock/commit/25059f7703ff36aed899342a39c7d80f2685daa6)), closes [#217](https://github.com/Landparty/mocky-mock/issues/217)
* **generate:** set a varying-length READ's DEPENDING ON item per row ([4c16518](https://github.com/Landparty/mocky-mock/commit/4c165188212ae099d6c7e11dc086a0850ff805a4)), closes [#214](https://github.com/Landparty/mocky-mock/issues/214)
* **generate:** surface the fixture bundle's unresolved warnings ([8a5cf07](https://github.com/Landparty/mocky-mock/commit/8a5cf073a6d96e5c1c01872ce7b49bb200501d4b)), closes [#331](https://github.com/Landparty/mocky-mock/issues/331)
* **generate:** treat a SORT's RELEASE/RETURN as expected placeholders ([488b961](https://github.com/Landparty/mocky-mock/commit/488b96177cb9d0e32c872fcea44f0dfb071fee1e)), closes [#262](https://github.com/Landparty/mocky-mock/issues/262)
* **generate:** use INITIALIZE as the ACCEPT placeholder body ([b2b8150](https://github.com/Landparty/mocky-mock/commit/b2b8150c0559bf769db120d55fd63dde00d6ecc5)), closes [#330](https://github.com/Landparty/mocky-mock/issues/330)
* **generate:** write a recordable STUB EXPECT for a WRITE's record ([d18d29a](https://github.com/Landparty/mocky-mock/commit/d18d29aa3e5e7c310530f021c1b1ef394d4b9857)), closes [#255](https://github.com/Landparty/mocky-mock/issues/255)
* **generate:** write only a SELECT/FETCH mock's INTO host variables ([dcb95d1](https://github.com/Landparty/mocky-mock/commit/dcb95d1db76663fbfcaba42d35ad3671366d4bed)), closes [#239](https://github.com/Landparty/mocky-mock/issues/239)
* **journal:** read entries back split on "\n" only ([bcd6289](https://github.com/Landparty/mocky-mock/commit/bcd6289311efb60ba56c47d08cb3c515cc43108d)), closes [#283](https://github.com/Landparty/mocky-mock/issues/283)
* **lint:** check one-line MOVE statements inside MOCK bodies ([3ea49d8](https://github.com/Landparty/mocky-mock/commit/3ea49d86e30b28840b7e4482e3663173a01355de)), closes [#243](https://github.com/Landparty/mocky-mock/issues/243)
* **lint:** check ROWS and TERMINAL field names and values ([ca10b36](https://github.com/Landparty/mocky-mock/commit/ca10b362d18e350b2695f9982baec97a9d4a1dfa)), closes [#299](https://github.com/Landparty/mocky-mock/issues/299)
* **lint:** know data names built through REPLACE pseudo-text ([99d1982](https://github.com/Landparty/mocky-mock/commit/99d19829ec275797198279665f67ca531a0964ce)), closes [#273](https://github.com/Landparty/mocky-mock/issues/273)
* **lint:** know only the UT- names this suite's driver declares ([9c60b6c](https://github.com/Landparty/mocky-mock/commit/9c60b6c601d878510669d095df5b0b149e989483)), closes [#296](https://github.com/Landparty/mocky-mock/issues/296)
* **lint:** refuse an EXPECT whose TRUE/FALSE form does not match the item's level ([5cf7bee](https://github.com/Landparty/mocky-mock/commit/5cf7beed7d9ea7a1bd42f655ead494b00db2d909)), closes [#307](https://github.com/Landparty/mocky-mock/issues/307)
* **lint:** warn when a case reaches an untestable omitted-argument test ([a86edb8](https://github.com/Landparty/mocky-mock/commit/a86edb8a311d1a80b847bb8468d7555636823e6c)), closes [#288](https://github.com/Landparty/mocky-mock/issues/288)
* **mock:** let a test pin ACCEPT FROM DATE/TIME, and never record the clock ([2b1a9f2](https://github.com/Landparty/mocky-mock/commit/2b1a9f20b92a16397aece633a87830c19c1af1cc)), closes [#240](https://github.com/Landparty/mocky-mock/issues/240)
* **mutate:** carry END-&lt;verb&gt; through the arithmetic verb swap ([b8e17e0](https://github.com/Landparty/mocky-mock/commit/b8e17e05fb3c5ee2245ca1933418d8b3359ba15c)), closes [#234](https://github.com/Landparty/mocky-mock/issues/234)
* **mutate:** never mutate a line inside a multi-line EXEC block ([18b779e](https://github.com/Landparty/mocky-mock/commit/18b779e10d4a84c673e3a3594a2635bb9ddd6927)), closes [#202](https://github.com/Landparty/mocky-mock/issues/202)
* **mutate:** no zero-baseline hint for ADD/SUBTRACT that runs in a loop ([4d2b6d8](https://github.com/Landparty/mocky-mock/commit/4d2b6d8dc59c4796dd1618e78a99e47587c775a2)), closes [#203](https://github.com/Landparty/mocky-mock/issues/203)
* **mutation:** map a mutant's line into the expanded AST for the loop check ([5a015a3](https://github.com/Landparty/mocky-mock/commit/5a015a39053b7f85e47fa23e570019c8abb96fc0)), closes [#342](https://github.com/Landparty/mocky-mock/issues/342)
* open bug-audit issues (WS reset, mutate, debugger, .cut parsing, lint) ([498dd28](https://github.com/Landparty/mocky-mock/commit/498dd282e47f58364fcee0a865354ac08b554ceb))
* **refusal:** accept a READ/RETURN ROWS mock whose AT END clause ends the loop ([a7beef2](https://github.com/Landparty/mocky-mock/commit/a7beef2c850b3bca972584921ab48e0019bdbf73)), closes [#341](https://github.com/Landparty/mocky-mock/issues/341)
* **refusal:** accept a REPLACE left in force to the end of the source ([44ca0c2](https://github.com/Landparty/mocky-mock/commit/44ca0c2b8322340035bd98cf9bcbec0d56ee6939)), closes [#272](https://github.com/Landparty/mocky-mock/issues/272)
* **refusal:** judge an EXEC SQL WHENEVER jump per case, not per program ([f1a37e0](https://github.com/Landparty/mocky-mock/commit/f1a37e0a5844de0ea26d60a848903ae150b901d9)), closes [#244](https://github.com/Landparty/mocky-mock/issues/244)
* **refusal:** refuse a mocked site whose clause bodies cannot be lifted ([ea6b817](https://github.com/Landparty/mocky-mock/commit/ea6b8170647bb4068f60b773caf7d67e83d0e288)), closes [#319](https://github.com/Landparty/mocky-mock/issues/319)
* **report:** attribute a PROVIDER template's assertions to each row ([ff7e05a](https://github.com/Landparty/mocky-mock/commit/ff7e05ab68a2094c6fa9b70c6963b5d34b202b77)), closes [#328](https://github.com/Landparty/mocky-mock/issues/328)
* **report:** count failed cases, not failed checks, in the console summary ([fda1e69](https://github.com/Landparty/mocky-mock/commit/fda1e69ce25b912e75c9bc0f55d617a92c5f2667)), closes [#235](https://github.com/Landparty/mocky-mock/issues/235)
* **report:** fail the run step when the suite never compiled ([388593f](https://github.com/Landparty/mocky-mock/commit/388593fe5dcfe8766f49fe6b4822fc57ce9fdb17)), closes [#260](https://github.com/Landparty/mocky-mock/issues/260)
* **report:** keep leading spaces of a failure's actual in the JSON report ([1e4c22f](https://github.com/Landparty/mocky-mock/commit/1e4c22fbcd3f60bb2d85991d4f70e702e6a5b6bb)), closes [#335](https://github.com/Landparty/mocky-mock/issues/335)
* **report:** let PERFORM &lt;section&gt; reach the section's paragraphs ([d25bf6f](https://github.com/Landparty/mocky-mock/commit/d25bf6f1d9f3338365563bf7e0d4e9b8a5864b41)), closes [#292](https://github.com/Landparty/mocky-mock/issues/292)
* **report:** match run results to same-named cases by .cut line ([d1fe868](https://github.com/Landparty/mocky-mock/commit/d1fe86828516d7b3ed2c05b1e034f094fd25f146)), closes [#304](https://github.com/Landparty/mocky-mock/issues/304)
* **report:** record-expectations goldens that fail on the next run ([5c201dc](https://github.com/Landparty/mocky-mock/commit/5c201dc1bce4907178a09a513a3605a643ef4798)), closes [#194](https://github.com/Landparty/mocky-mock/issues/194)
* **reset:** reset USAGE INDEX items and PICTURE-less binary/float usages ([b8fb9d6](https://github.com/Landparty/mocky-mock/commit/b8fb9d600e53b06fe90749d605c748d9c690892c)), closes [#333](https://github.com/Landparty/mocky-mock/issues/333)
* **run:** give an unnamed PROCEDURE DIVISION main line its own paragraph ([d8aff2b](https://github.com/Landparty/mocky-mock/commit/d8aff2bf09720eef0d51d515e26d04ece5909ba2)), closes [#264](https://github.com/Landparty/mocky-mock/issues/264)
* **run:** keep a CRLF .cut CRLF when --record-expectations rewrites it ([1f2dee6](https://github.com/Landparty/mocky-mock/commit/1f2dee69c709097886b6d7789e6dd32c84a3f754)), closes [#199](https://github.com/Landparty/mocky-mock/issues/199)
* **run:** record a level-88 stub as TRUE/FALSE and an index-name as its occurrence ([63d24f9](https://github.com/Landparty/mocky-mock/commit/63d24f963f34cd430d6b1b94245161e526a58694)), closes [#237](https://github.com/Landparty/mocky-mock/issues/237)
* **run:** rejoin a FAIL/RECORD value split at an X'0A' byte ([702b0d6](https://github.com/Landparty/mocky-mock/commit/702b0d6632694dd6684b3e0e93e852df05603306)), closes [#285](https://github.com/Landparty/mocky-mock/issues/285)
* second bug-audit sweep, every remaining medium and low issue plus the late highs (87 issues) ([d3a983d](https://github.com/Landparty/mocky-mock/commit/d3a983dd76af90fbf5085162e092f1bd9095d111))
* **splicer:** byte-copy edited items in the BEFORE-ALL snapshot ([0d45f54](https://github.com/Landparty/mocky-mock/commit/0d45f54cf56d94a5187ba57162a4d0fc6bc1b61c)), closes [#224](https://github.com/Landparty/mocky-mock/issues/224)
* **splicer:** carry INDEXED BY indexes through the BEFORE-ALL snapshot ([9aafc43](https://github.com/Landparty/mocky-mock/commit/9aafc4390dc03bc4a1f536b30b5cd8b931bddb00)), closes [#280](https://github.com/Landparty/mocky-mock/issues/280)
* **splicer:** clear a VALUE-less FILLER when resetting its group ([71b2de4](https://github.com/Landparty/mocky-mock/commit/71b2de4eccfc1c5810214dcc0e2c0e46e08537b3)), closes [#278](https://github.com/Landparty/mocky-mock/issues/278)
* **splicer:** copy alphanumeric-edited values as bytes in reset, rows and captures ([baec76e](https://github.com/Landparty/mocky-mock/commit/baec76e5313453312e4438e629d439277dad55cc)), closes [#277](https://github.com/Landparty/mocky-mock/issues/277)
* **splicer:** default a mocked EXEC CICS command's RESP to NORMAL ([b6bae8c](https://github.com/Landparty/mocky-mock/commit/b6bae8cb3cb8123cbb7a0f9c300117e2b4747560)), closes [#320](https://github.com/Landparty/mocky-mock/issues/320)
* **splicer:** emit lifted clause bodies verbatim so they stay mapped ([fdd77c1](https://github.com/Landparty/mocky-mock/commit/fdd77c1ef7190e55cad156a610efb7697df03825)), closes [#332](https://github.com/Landparty/mocky-mock/issues/332)
* **splicer:** emulate EXEC SQL WHENEVER instead of mocking it ([9105bec](https://github.com/Landparty/mocky-mock/commit/9105bec189c005f9875f51d2c7e2e9d6f6a4eeb4)), closes [#195](https://github.com/Landparty/mocky-mock/issues/195)
* **splicer:** end the run after a mocked EXEC CICS RETURN/XCTL/ABEND ([8bef33e](https://github.com/Landparty/mocky-mock/commit/8bef33e4d29b63cbf36999ba01e4e0f5fb890c9f)), closes [#215](https://github.com/Landparty/mocky-mock/issues/215)
* **splicer:** exit the whole SECTION from a chain check in its first paragraph ([f097328](https://github.com/Landparty/mocky-mock/commit/f097328765ffe8f063c73a1d6cf7b842cd829271)), closes [#338](https://github.com/Landparty/mocky-mock/issues/338)
* **splicer:** give the synthesized SQLCA its SQLEXT group (136 bytes) ([010d9e0](https://github.com/Landparty/mocky-mock/commit/010d9e08454141573cbbfe8b9607200c045e4ae9)), closes [#271](https://github.com/Landparty/mocky-mock/issues/271)
* **splicer:** keep a STOP RUN/GOBACK RETURNING operand when neutralizing ([6850d87](https://github.com/Landparty/mocky-mock/commit/6850d87ed69351735af86315ecdbec9716051373)), closes [#219](https://github.com/Landparty/mocky-mock/issues/219)
* **splicer:** keep SET ADDRESS OF as a real rebind when the address is the program's own ([55490b4](https://github.com/Landparty/mocky-mock/commit/55490b4ad786eab5e11ba064d61ebe73808270dd)), closes [#226](https://github.com/Landparty/mocky-mock/issues/226)
* **splicer:** keep the ROWS cursor across hook steps; VERIFY via a baseline ([f7cc4fc](https://github.com/Landparty/mocky-mock/commit/f7cc4fcf737c934ebf156973af2e6ddc2f5c9bd0)), closes [#223](https://github.com/Landparty/mocky-mock/issues/223)
* **splicer:** leave FILLER out of an ODO counter's qualified name ([0d9a6c5](https://github.com/Landparty/mocky-mock/commit/0d9a6c50d1a5eb3f64a8bcaf05c014205f7761a3)), closes [#246](https://github.com/Landparty/mocky-mock/issues/246)
* **splicer:** let a mocked NOHANDLE CICS terminator return control on failure ([517b51c](https://github.com/Landparty/mocky-mock/commit/517b51cc0a7a228dda6a687b60b9f979b6404ee1)), closes [#301](https://github.com/Landparty/mocky-mock/issues/301)
* **splicer:** make every tally name a pure function of (category, key) ([129cc95](https://github.com/Landparty/mocky-mock/commit/129cc9538ec2e9f0e55676e25fdd2d0593d74481)), closes [#314](https://github.com/Landparty/mocky-mock/issues/314)
* **splicer:** mocked WRITE/REWRITE set the file's FILE STATUS ([6000eee](https://github.com/Landparty/mocky-mock/commit/6000eeef7fc412ea7621590bdc5101ee0631e988)), closes [#221](https://github.com/Landparty/mocky-mock/issues/221)
* **splicer:** negate a combined EXPECT condition as a whole ([63e8f01](https://github.com/Landparty/mocky-mock/commit/63e8f0153763ecdc3f8f3f9618e9a7abdeecb8b9)), closes [#265](https://github.com/Landparty/mocky-mock/issues/265)
* **splicer:** never comment out a compiler-directing line after a spliced statement ([bdeb90e](https://github.com/Landparty/mocky-mock/commit/bdeb90eeca9098b53e1d03affa0d04329cb9ccae)), closes [#310](https://github.com/Landparty/mocky-mock/issues/310)
* **splicer:** never name an ambiguous top-level item bare in the reset or snapshot ([aba6505](https://github.com/Landparty/mocky-mock/commit/aba65052015073922572e2220f39987ce06bc190)), closes [#281](https://github.com/Landparty/mocky-mock/issues/281)
* **splicer:** place a nested chain PERFORM's early-exit check inside its branch ([95b85ac](https://github.com/Landparty/mocky-mock/commit/95b85ac3ce2b18d1f71e60da645e6be71b623f79)), closes [#337](https://github.com/Landparty/mocky-mock/issues/337)
* **splicer:** qualify an INDEXED BY name two tables declare ([df6e992](https://github.com/Landparty/mocky-mock/commit/df6e9927d93b2aec3da595e73cabd6cfb4992bcd)), closes [#249](https://github.com/Landparty/mocky-mock/issues/249)
* **splicer:** qualify group-child VALUE restores in the WS reset ([3150e9f](https://github.com/Landparty/mocky-mock/commit/3150e9f0af0cb94712519466e81e48636d0069e6)), closes [#220](https://github.com/Landparty/mocky-mock/issues/220)
* **splicer:** recognize a literal CALL argument next to a subscripted operand ([066906b](https://github.com/Landparty/mocky-mock/commit/066906b440f774a42a067954c49336484bdcffc0)), closes [#291](https://github.com/Landparty/mocky-mock/issues/291)
* **splicer:** report SQLSTATE from a MOCK SQL ... ROWS mock ([935ffae](https://github.com/Landparty/mocky-mock/commit/935ffaeeefb8b05c37e4ef4f2e44b171f2dadb7a)), closes [#313](https://github.com/Landparty/mocky-mock/issues/313)
* **splicer:** reset and snapshot the named items under a FILLER group ([f7ec230](https://github.com/Landparty/mocky-mock/commit/f7ec230c842861ae3628576f788a93fcdf7f9051)), closes [#247](https://github.com/Landparty/mocky-mock/issues/247)
* **splicer:** reset INDEXED BY indexes between cases; support EXPECT &lt;88&gt; TO BE TRUE ([5d112db](https://github.com/Landparty/mocky-mock/commit/5d112dba0e8b8d74d37622a224d78a8a0cd21326)), closes [#189](https://github.com/Landparty/mocky-mock/issues/189)
* **splicer:** reset OCCURS DEPENDING ON tables at their maximum size ([9bde545](https://github.com/Landparty/mocky-mock/commit/9bde545e9987f1ab11c7c95aaaf105b24842a6bb)), closes [#216](https://github.com/Landparty/mocky-mock/issues/216)
* **splicer:** restore FILLER VALUEs in the WORKING-STORAGE reset ([b45e2ca](https://github.com/Landparty/mocky-mock/commit/b45e2cade12c2505913b1efcfe05f7e9e1d6110f)), closes [#196](https://github.com/Landparty/mocky-mock/issues/196)
* **splicer:** restore numeric-edited and JUSTIFIED VALUEs byte-faithfully ([54e1ab6](https://github.com/Landparty/mocky-mock/commit/54e1ab6f3f7a55aa03806dc14e9f1c4fb0ff2d03)), closes [#218](https://github.com/Landparty/mocky-mock/issues/218)
* **splicer:** run a mocked statement's own clause bodies by its outcome ([a82ec38](https://github.com/Landparty/mocky-mock/commit/a82ec389280a730f0b28dafc5a3f62a4d98a2109)), closes [#209](https://github.com/Landparty/mocky-mock/issues/209)
* **splicer:** snapshot the synthesized EIB, DIB and SQLCA around BEFORE-ALL ([290ca2c](https://github.com/Landparty/mocky-mock/commit/290ca2c8555b40fca03b153fbb5ba13c599621fa)), closes [#225](https://github.com/Landparty/mocky-mock/issues/225)
* **splicer:** splice a nested READ/CALL bounded by its own END-xxx ([6689692](https://github.com/Landparty/mocky-mock/commit/66896922b1d1d9dfbf808497d46a27e00d971de0)), closes [#258](https://github.com/Landparty/mocky-mock/issues/258)
* **splicer:** splice a nested RETURN ... END-RETURN like a nested READ ([62f66cc](https://github.com/Landparty/mocky-mock/commit/62f66cc885cd0ab2df454a23726aa029517c6d98)), closes [#340](https://github.com/Landparty/mocky-mock/issues/340)
* **splicer:** splice TRUE/FALSE assigned to a level-88 as SET, not MOVE ([aca6d9f](https://github.com/Landparty/mocky-mock/commit/aca6d9f3bb34f669957d2e2235c58001b71d25bc)), closes [#251](https://github.com/Landparty/mocky-mock/issues/251)
* **splicer:** split long EXPECT/MOVE literals across driver lines ([3ccde53](https://github.com/Landparty/mocky-mock/commit/3ccde5350f28bb9e62d68d7bc6a55e8e803662d2))
* **splicer:** split long literals in hook MOVEs, ROWS and mock bodies ([7b4edfa](https://github.com/Landparty/mocky-mock/commit/7b4edfa8d94132830ad13f0a7e14d9200cade498)), closes [#322](https://github.com/Landparty/mocky-mock/issues/322)
* **trace:** keep procedure-copybook statements in the executed path ([3f1cc2b](https://github.com/Landparty/mocky-mock/commit/3f1cc2bea893665c7005ba21badf6613b86267a4)), closes [#242](https://github.com/Landparty/mocky-mock/issues/242)
* **trace:** scope run --trace to the selected case's own span ([f73c645](https://github.com/Landparty/mocky-mock/commit/f73c645ce00ea10e2ef8d4139de3d8556d75a107)), closes [#334](https://github.com/Landparty/mocky-mock/issues/334)
* write comma-decimal literals for DECIMAL-POINT IS COMMA programs ([1378402](https://github.com/Landparty/mocky-mock/commit/13784025d30bcca0a209a7fafb5344dbb1f0c599)), closes [#230](https://github.com/Landparty/mocky-mock/issues/230)


### Documentation

* **okf:** log the 2026-10-16 bug-audit sweep ([a796c6d](https://github.com/Landparty/mocky-mock/commit/a796c6d55f1a4f8a53559058ec94e9ee3ee8e252))
* **okf:** log the second bug-audit sweep ([f6b1b40](https://github.com/Landparty/mocky-mock/commit/f6b1b40fec3f5c4d1f7c30c3ede31f4d64af9b09))

## [0.10.1](https://github.com/Landparty/mocky-mock/compare/v0.10.0...v0.10.1) (2026-10-14)


### Bug Fixes

* **cli:** give each of a program's several suites its own report file ([fc1344e](https://github.com/Landparty/mocky-mock/commit/fc1344e55aa738495dcc2f4b92e412e2e3e52e12))
* **cli:** give each of a program's several suites its own report file ([5c2b067](https://github.com/Landparty/mocky-mock/commit/5c2b067774998a8629542d322ff4e48f46d84b92))

## [0.10.0](https://github.com/Landparty/mocky-mock/compare/v0.9.0...v0.10.0) (2026-10-14)


### Features

* flag cases that assert nothing; default generate to one case per scenario ([79f3734](https://github.com/Landparty/mocky-mock/commit/79f373484a19c56944edacb1da8e7c33d3d8b6e9))
* several suites per program, and suites under tests/ ([1f91d56](https://github.com/Landparty/mocky-mock/commit/1f91d56d905d765a610765a2cb8894ac0c2dfb28))


### Bug Fixes

* sync __version__ and plugin.json to 0.9.0; use release-please's generic updater ([80b699c](https://github.com/Landparty/mocky-mock/commit/80b699caa6c011b3ab865887053c103b2c39299f))

## [0.9.0](https://github.com/Landparty/mocky-mock/compare/v0.8.0...v0.9.0) (2026-09-15)


### Features

* **refusal:** pin every Enterprise COBOL program type; honest nested-program and DECLARATIVES refusals ([09803b0](https://github.com/Landparty/mocky-mock/commit/09803b04571a6718e7c68a720bb4e51b16565c70))


### Bug Fixes

* back UNSUPPORTED_DECLARATIVES with a USE-statement fallback ([f1d24ca](https://github.com/Landparty/mocky-mock/commit/f1d24ca528098565f3fad41714b63eb77e27606d))


### Documentation

* correct the FieldSpec "mirrored" claim in the interface contract ([44adf27](https://github.com/Landparty/mocky-mock/commit/44adf2763da88506dbc37d7298666b543c1a6610))
* design plan for .cut editor completion, hover, and quick fixes ([5c3bd49](https://github.com/Landparty/mocky-mock/commit/5c3bd49aca78e0b2f6d92649ab9ab55700a6d5ff))
* design plans for a more approachable CLI/DSL onboarding path ([0ed1925](https://github.com/Landparty/mocky-mock/commit/0ed192502c5e8cc57fa94562c912f88ece215e82))
* record cobol-parser's new copybook record-image formats ([b0d5235](https://github.com/Landparty/mocky-mock/commit/b0d5235359c8e1f895cebb9a57448f5d95b69130))
* record cobol-parser's new copybook record-image formats ([73f030a](https://github.com/Landparty/mocky-mock/commit/73f030a8d4a622567ae3440e07833ad39871bc85))
* seventh project audit — nine findings, none fixed ([b71aaa6](https://github.com/Landparty/mocky-mock/commit/b71aaa667b7fded19bb837a1f10262d280711fb6))

## [0.8.0](https://github.com/Landparty/mocky-mock/compare/v0.7.0...v0.8.0) (2026-09-04)


### Features

* **generate:** scaffold CAPTURE ARG, and synthesize the storage it needs ([25076e0](https://github.com/Landparty/mocky-mock/commit/25076e01911e569e165c8a7cf9677adf878434b9))
* **generate:** surface cobol-parser's unverified-scenario verdict in the generated .cut ([bec5a85](https://github.com/Landparty/mocky-mock/commit/bec5a85b02282396330820d270d6daaf3adafe23))
* lead coverage with the original program's number, gate CI on it, and explain stillborn mutants ([073d4f7](https://github.com/Landparty/mocky-mock/commit/073d4f7b9763b96e2725b947ac1d2e5cb4f9aea9))
* **mutate:** coverage gate and --jobs, the two mutation cost levers ([2127755](https://github.com/Landparty/mocky-mock/commit/212775556c6207588f671910b710ecca0dd94d7b))
* refuse or mock every COBOL dependency cobol-parser now parses ([0fc46f2](https://github.com/Landparty/mocky-mock/commit/0fc46f28a6ed2a5852874d85300b320646c215eb))


### Bug Fixes

* address four review findings on the capture/export/coverage work ([1a8daea](https://github.com/Landparty/mocky-mock/commit/1a8daea47cce20c57a29b980d899f94c36417879))
* correct VERIFY syntax in design note; cover all three exhaustion paths ([d343d9b](https://github.com/Landparty/mocky-mock/commit/d343d9b798e7ce0990b6fd4faf1011e47f6bbcd4))
* **export:** continue a long literal instead of refusing the line ([4c9838f](https://github.com/Landparty/mocky-mock/commit/4c9838fea95c2282d80723afcaf80551f73763d5))
* **export:** name the two literal-continuation failure modes apart ([26e3624](https://github.com/Landparty/mocky-mock/commit/26e36249ad669f015d801a7d9b63fa8f21f4d745))
* **export:** wrap over-long lines instead of refusing, and name the real overflow source ([c7fef8f](https://github.com/Landparty/mocky-mock/commit/c7fef8f920da5ae7ce395d1977d90755d1670159))
* **generate:** emit real READ exhaustion arms and stop dropping boundary stub expectations ([9fc8f7d](https://github.com/Landparty/mocky-mock/commit/9fc8f7d83eb57e041b8794fdfc1c9fc755a142e8))
* **generate:** replicate AT END SET &lt;88&gt; TO TRUE into READ mock exhaustion ([625eec0](https://github.com/Landparty/mocky-mock/commit/625eec0cdf627fd4a7cc3a77459afa0e3aa84e6b))
* **mutate:** stop generating mutants that cannot compile ([6ef9fee](https://github.com/Landparty/mocky-mock/commit/6ef9fee462cebede685d064220021f36faac89f5))
* **mutate:** type the stillborn reason as a literal, not a narrowed str ([b193603](https://github.com/Landparty/mocky-mock/commit/b1936032803b61f6c6ad8c44a04fc221a8dca1da))


### Documentation

* **mutate:** say what _sequence_area_end actually returns ([e63320a](https://github.com/Landparty/mocky-mock/commit/e63320abdcfcd415ec7967087bb892c4e4940359))
* record that generated scenarios never assert which branch they reach ([f45e228](https://github.com/Landparty/mocky-mock/commit/f45e2286a75cc87a5e77067318ebddaf95f97d3d))

## [0.7.0](https://github.com/Landparty/mocky-mock/compare/v0.6.4...v0.7.0) (2026-09-01)


### Features

* **cics:** synthesize DFHEIBLK EIB fields and generalize LINKAGE neutralization to no-ENTRY programs ([4623b25](https://github.com/Landparty/mocky-mock/commit/4623b254f6dcca13e48904b893b17aa9762afc89))
* consume cobol-parser from PyPI, publish mockymock to PyPI ([eb76616](https://github.com/Landparty/mocky-mock/commit/eb766167137343d08d4795c2253529c6cf765d0e))
* EXPECT negation and comparison operators in the .cut DSL ([97aaf0c](https://github.com/Landparty/mocky-mock/commit/97aaf0cd7e85088f646dad075607a42a475ac173))
* mock plain-file-form SORT/MERGE (USING ... GIVING ...) ([7872a68](https://github.com/Landparty/mocky-mock/commit/7872a68252773fdd61c3d64e49030658f9116fcf))
* mock SORT/MERGE (USING/GIVING form + RELEASE/RETURN) ([989784e](https://github.com/Landparty/mocky-mock/commit/989784e3d2f17a19da8f3df7f5230de8e0c7d3b2))
* mock SORT/MERGE's INPUT/OUTPUT PROCEDURE form via RELEASE/RETURN ([a32c20e](https://github.com/Landparty/mocky-mock/commit/a32c20ef8b4b4173d9d8bc6108177b41eddd621a))


### Bug Fixes

* **analysis:** resolve botched merge leaving stale refusal package ([d802f0c](https://github.com/Landparty/mocky-mock/commit/d802f0c3801e8878dc3c963d48703dccee919cc2))
* **analysis:** resolve transitive GO-TO-exit fallthrough chains to a fixpoint ([46aa88a](https://github.com/Landparty/mocky-mock/commit/46aa88a8f313053712b4a4d91414e24db1522caf))
* **analysis:** stop GO TO fall-through cascade past a safely-entered section ([63b8e69](https://github.com/Landparty/mocky-mock/commit/63b8e69b40bfce096364f163a98785250c1bfaea))
* **analysis:** stop GO-TO-exit fall-through cascade in reachability gates ([25965c0](https://github.com/Landparty/mocky-mock/commit/25965c099e8d3499ba34879ede51586486ae7a79))
* **cics:** COBOL-aware word boundaries and case-insensitive EIB/DFHCOMMAREA/DFHRESP matching ([cc07964](https://github.com/Landparty/mocky-mock/commit/cc07964f66a6d7a1e225f775d5d0d81da29eb1c0))
* correct project name in pyproject.toml ([e26373b](https://github.com/Landparty/mocky-mock/commit/e26373be1a1063579689ae854320f1490da91503))
* correct scenario_coverage documentation in scenario-generation.md ([2b2689f](https://github.com/Landparty/mocky-mock/commit/2b2689f419a2565ed24732c736f352ba85d0cb5a))
* disable test suite in CI due to long execution time ([930b391](https://github.com/Landparty/mocky-mock/commit/930b391736dc0c7e14f52eb93bb9b18bdcd235d3))
* **linkage:** read LINKAGE SECTION header line from CobolSection.location ([6d52232](https://github.com/Landparty/mocky-mock/commit/6d522326da3714596535cfc23261df3e023818d2))
* prevent recommending --scenarios branches when all arms are missed ([5ff55b6](https://github.com/Landparty/mocky-mock/commit/5ff55b607b598c447da2485c771ad3c56965cdbe))
* **refusal:** scope UNSUPPORTED_CICS_MACRO by reachability ([2df9002](https://github.com/Landparty/mocky-mock/commit/2df9002303946bbb098b62904c06b069f8b3722f))
* **refusal:** tolerate phantom "." paragraphs in goto-exit adjacency check ([c8124f7](https://github.com/Landparty/mocky-mock/commit/c8124f77fee8f4de41b0845fa051dc85fb545652))
* regenerate stale uv.lock pinning cobolparser to a July git SHA ([e305e1f](https://github.com/Landparty/mocky-mock/commit/e305e1f598fc289099e829a318d1ba2a621cba1b))
* **runtime:** add -std=mvs so cobc compiles EJECT/SKIP1-3 sources ([ecc7dbe](https://github.com/Landparty/mocky-mock/commit/ecc7dbeacf4de9ac410e8c2a9d40fef114c0b416))
* **splicer:** repair two compile-blocking codegen bugs from the corpus ([69ce403](https://github.com/Landparty/mocky-mock/commit/69ce403b849d04ff77e0de21f356dd5026f141b4))
* **splicer:** validate replace_columns' span against the line ([1a11c8b](https://github.com/Landparty/mocky-mock/commit/1a11c8bbce099362e458a0c87d42c71198eee9af))


### Performance Improvements

* **analysis:** remove the quadratic scans from the static-check pass ([cc1f17e](https://github.com/Landparty/mocky-mock/commit/cc1f17e2d2dd5bdd24b1a0ba1353fff25fc25304))


### Documentation

* add scenario-generation reference for the mockymock skill ([9cbd3c7](https://github.com/Landparty/mocky-mock/commit/9cbd3c7c91a4571f868868554b1a0e04307a81a6))
* fix OUT-boundary filter and overclaims in scenario-generation.md ([635fec3](https://github.com/Landparty/mocky-mock/commit/635fec32803b3ad7fe7bdcbc782f9d1ca40cccfe))
* teach the mockymock skill to reason about scenario generation ([e5f3b0e](https://github.com/Landparty/mocky-mock/commit/e5f3b0e04d77333b7f251ce5f032884abe98a68d))
* update OKF for scenario-generation skill enrichment ([98c54f5](https://github.com/Landparty/mocky-mock/commit/98c54f5d3385e10570cd98dbe57ef73eed77a305))

## [0.6.4](https://github.com/Landparty/mocky-mock/compare/v0.6.3...v0.6.4) (2026-08-14)


### Bug Fixes

* cache Nuitka onefile extraction across CLI launches ([2952a95](https://github.com/Landparty/mocky-mock/commit/2952a951fa35be09506d310d2c00b01be7112567))
* cache Nuitka onefile extraction across CLI launches ([6cd6f81](https://github.com/Landparty/mocky-mock/commit/6cd6f81e2afd0bb135d396a02e4f4aa9b252af75))

## [0.6.3](https://github.com/Landparty/mocky-mock/compare/v0.6.2...v0.6.3) (2026-08-13)


### Bug Fixes

* lead GO TO/fall-through terminator refusals with the COBOL cause, not the mechanism ([33f0c2f](https://github.com/Landparty/mocky-mock/commit/33f0c2ff5a13cbf2bc1e0b2ce0796b12ae5b8b21))

## [0.6.2](https://github.com/Landparty/mocky-mock/compare/v0.6.1...v0.6.2) (2026-08-13)


### Bug Fixes

* run reports on refusal/compile failure, add --timeout, fix fixture-bundle type gap ([c00c4d2](https://github.com/Landparty/mocky-mock/commit/c00c4d29dd76b24bece61208f290872c0fc9c071))

## [0.6.1](https://github.com/Landparty/mocky-mock/compare/v0.6.0...v0.6.1) (2026-08-12)


### Bug Fixes

* close the reachability BFS over GO TO fall-through ([b5301ce](https://github.com/Landparty/mocky-mock/commit/b5301ce2be1e04e93e8695ebecba2ae62e49f3e8))
* close the reachability BFS over GO TO fall-through ([162f205](https://github.com/Landparty/mocky-mock/commit/162f2050b5f2179448ed93cb6fb59431806d5815))
* key orphan-record skip diagnosis on (case_id, data_name) ([dc95c4d](https://github.com/Landparty/mocky-mock/commit/dc95c4d7fda5a70043acec47a6b899f4480214d4))
* remediate 19 of the 2026-08-12 audit's 20 findings, TDD at the pin ([a9c7ba6](https://github.com/Landparty/mocky-mock/commit/a9c7ba68d93ad14ebed76cd5def4d3c2a17e31ea))


### Documentation

* sixth framework audit — 20 new findings, none fixed ([04fccda](https://github.com/Landparty/mocky-mock/commit/04fccdaf6dd3c42ef2624c548fbbe5cda50072e7))

## [0.6.0](https://github.com/Landparty/mocky-mock/compare/v0.5.2...v0.6.0) (2026-08-11)


### Features

* add CAPTURE ARG &lt;n&gt; INTO &lt;target&gt; grammar to MOCK CALL bodies ([18b7ca7](https://github.com/Landparty/mocky-mock/commit/18b7ca785e19a69c0ae3f468f1fb15789142d865))
* refuse CAPTURE_ARG_OUT_OF_RANGE when a CAPTURE index exceeds a site's real USING-parameter count ([b8c6654](https://github.com/Landparty/mocky-mock/commit/b8c6654fa5db08984a3cd931e6e22fcba44ff8a1))
* splice CAPTURE ARG's resolved MOVE before a CALL/DYNCALL mock's body lines ([ff22fbb](https://github.com/Landparty/mocky-mock/commit/ff22fbb66943468fcacc620691c824be4e331639))


### Bug Fixes

* add fail-closed guard for malformed CAPTURE statements + test coverage ([c8da6fa](https://github.com/Landparty/mocky-mock/commit/c8da6fa9ea4bd9ea1bd004ddac05b41b49770f5c))
* check AMBIGUOUS_MOCK (and nested/layout checks) against every matching site program-wide ([3e0c286](https://github.com/Landparty/mocky-mock/commit/3e0c286164f968b22f8ca5ccd1333d183025057c))
* check AMBIGUOUS_MOCK against every matching site program-wide ([251d9e8](https://github.com/Landparty/mocky-mock/commit/251d9e87adff8d875d88d6e3835a98473acd2649))
* check CAPTURE_ARG_OUT_OF_RANGE against every matching site program-wide ([723079b](https://github.com/Landparty/mocky-mock/commit/723079bcc846f94d4ca8a85f7ffd7347b4fa35e1))
* handle oversized CAPTURE ARG index parse errors and align design doc semantics ([c45aad4](https://github.com/Landparty/mocky-mock/commit/c45aad49f0873de58fe5fda9a4c49d48da8e1fa4))
* resolve audit doc contradiction and refresh OKF timestamps ([95ff0fd](https://github.com/Landparty/mocky-mock/commit/95ff0fda6fb533f25d5d8ff57d6d243e561926ef))


### Documentation

* demonstrate CAPTURE ARG in the ordrproc worked example, proven via Docker ([b4cbb8a](https://github.com/Landparty/mocky-mock/commit/b4cbb8a3825006846dd225833302a02a66fedf87))
* document CAPTURE ARG argument capture across OKF bundle, AI skill, and audit doc ([a3fbcaf](https://github.com/Landparty/mocky-mock/commit/a3fbcaf76d560da57f1daf5a302dac4ca70bc9d5))
* mark argument capture closed in the 2026-08-10 framework audit roadmap ([513ba7a](https://github.com/Landparty/mocky-mock/commit/513ba7ab8b31762ed282202e2a47f5023ae1ad8b))

## [0.5.2](https://github.com/Landparty/mocky-mock/compare/v0.5.1...v0.5.2) (2026-08-11)


### Bug Fixes

* 47 stale downstream VERIFY counts, add [#48](https://github.com/Landparty/mocky-mock/issues/48) Docker coverage for READ ROWS/TERMINAL ([7e0ee64](https://github.com/Landparty/mocky-mock/commit/7e0ee64a878c844a05113b629d8bd3050cd5e399))
* Replace verbose Gotchas section with condensed pointer list to .okf/ ([b8696e5](https://github.com/Landparty/mocky-mock/commit/b8696e5100d9c3ba790b0b3394058e5469f9c6cf))
* Restore 6th gotcha (Docker tests) and use quote-based references instead of ordinals ([c7ec53f](https://github.com/Landparty/mocky-mock/commit/c7ec53ff94f825d969cfb6c91909372edc633c18))

## [0.5.1](https://github.com/Landparty/mocky-mock/compare/v0.5.0...v0.5.1) (2026-08-10)


### Documentation

* fix stale org references in install instructions ([a6bdab8](https://github.com/Landparty/mocky-mock/commit/a6bdab88cee56ebc3d9a0f319f8c9dace9b49a5c))
* fix stale present-tense claims and commit citation from prior pass ([4a13386](https://github.com/Landparty/mocky-mock/commit/4a13386bd783f3bf27f13e1a269052ca8b5b6236))
* fix whole-branch review accuracy defects vs sibling repo's actual workflow ([fda5926](https://github.com/Landparty/mocky-mock/commit/fda59265fdb449e53d72150fe92413e33b61fe18))
* update publishing docs for the retired standalone pipeline ([fd9a7b4](https://github.com/Landparty/mocky-mock/commit/fd9a7b4e645a798effe1d5222fede395c5365302))

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
