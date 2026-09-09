# Linux-specific known-failure rules

Rule files in this directory use the same JSON format as `Data/KnownFailures/`
and are layered on top of it by passing `--known-failures-dir` twice:

```
RunIntegrationTests.py ... \
  --known-failures-dir Data/KnownFailures \
  --known-failures-dir Data/KnownFailuresLinux
```

Scope note: known-failure rules match **metric differences** (section, object
pattern, metric pattern). They cannot express run-level *errors* such as a
crash or a hung load, because those never reach the comparison stage. The two
currently known Linux-only issues are both errors of that kind and are
therefore not represented here:

- `GX_NeckLedHolder` -- SIGSEGV in OCCT curve bounding on Linux only.
- `FPL_LED5mm` -- intermittent empty-document open on Linux.

Callers that need to tolerate those must post-process the run's
`FAILURES_JSON` output (the private cloud-sweep driver does this via its
`LinuxSweepExpected` list). If a Linux-only **metric** deviation is ever
found, its rule belongs in this directory.
