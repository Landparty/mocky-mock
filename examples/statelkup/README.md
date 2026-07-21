# STATELKUP

Demonstrates `PROVIDER`/`HEADER`/`ROW` parameterized test cases: one
`TESTCASE "..." USING PROVIDER StateNames` expands, at parse time, into
three ordinary test cases -- one per `ROW` -- each substituting
`{Abbreviation}`/`{Name}` into its `MOVE`/`EXPECT` values.

Run it:

```bash
mockymock collect --cut STATELKUP.cut
mockymock run STATELKUP.cbl --cut STATELKUP.cut
```

`collect` lists three cases even though the `.cut` file only has one
`TESTCASE` line:

```
TESTCASE '1000-LOOKUP-STATE resolves a state name [row 1: AZ]' (line 5)
TESTCASE '1000-LOOKUP-STATE resolves a state name [row 2: KY]' (line 6)
TESTCASE '1000-LOOKUP-STATE resolves a state name [row 3: XX]' (line 7)
```

The third row (`XX` -> `*Undefined*`) exercises `EVALUATE`'s `WHEN OTHER`
branch -- proving the three generated cases are genuinely independent,
not three copies of the same assertion.

See [../../docs/2026-07-20-provider-parameterized-test-cases-design.md](../../docs/2026-07-20-provider-parameterized-test-cases-design.md)
for the full design.
