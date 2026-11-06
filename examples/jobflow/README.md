# jobflow: a whole JCL job, run end to end

`jcl/CUSTJOB.jcl` runs four steps:

1. `CLEANUP` (IEFBR14) deletes last run's report.
2. `EXTRACT` (`src/CUSTEXT.cbl`) copies the customers whose balance is over 100 from `PROD.CUST.MASTER` to a temporary dataset, logs the run to DB2 (mocked), and ends with RC 4 when it kept none.
3. `SORTHI` (SORT) sorts them by name, unless EXTRACT ended with RC 4 or more (`COND=(4,LE,EXTRACT)`).
4. `REPORT` (`src/CUSTRPT.cbl`) writes `PROD.CUST.REPORT` with a total line.

```bash
pip install 'mockymock[jcl]'
cd examples/jobflow
mockymock job jcl/CUSTJOB.jcl --src src --data data --expected expected
```

`data/PROD.CUST.MASTER` is the input dataset (20-byte records); `expected/PROD.CUST.REPORT` was recorded with `--record`. Change a balance in the input or the limit in CUSTEXT and the run fails, naming the first record of the report that differs. With an input where no balance is over 100, EXTRACT ends with RC 4 and the run shows SORTHI and REPORT bypassed.
