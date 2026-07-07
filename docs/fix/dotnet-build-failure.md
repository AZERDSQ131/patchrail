<!-- Canonical: https://getpatchrail.com/fix/dotnet-build-failure -->

# .NET build failures — NU1605 / NETSDK / CS errors

> Part of the **CI Failure Triage** field guide. The canonical, formatted version of this page lives at **[getpatchrail.com/fix/dotnet-build-failure](https://getpatchrail.com/fix/dotnet-build-failure)**.

## Log signatures

These are the literal strings to search for in the failed log:

```text
error NU1605: Detected package downgrade
error NETSDK1045: The current .NET SDK does not support targeting
error CS0246: The type or namespace name could not be found
Version conflict detected
Build FAILED
```

## What actually happened

The error code prefix tells you the layer, and that's the triage: NU____ (NuGet) — restore-time dependency problems; NU1605 package downgrade and Version conflict detected mean two projects in the solution pin different versions of one package. NETSDK____ — SDK/target-framework mismatch, the CI image's .NET SDK can't build the project's TargetFramework (e.g. project targets net9.0, image has SDK 8). CS____ (C# compiler) — a real compile error in your code. Xunit.Sdk / "Failed!  - Failed:" — compilation succeeded; a test failed, a different problem entirely.

## Fix it

1. Grep the log for the first NU, NETSDK, or CS code and route accordingly.
2. NETSDK errors: check global.json vs the SDK installed in CI (dotnet --list-sdks). Align one of them deliberately.
3. NU conflicts: consolidate the package version across projects — central package management (Directory.Packages.props) makes the whole class structurally impossible.
4. CS errors: ordinary compile fix; look up the code (they're well documented) and fix the narrowest site.
5. Test failures: reproduce with dotnet test --filter "FullyQualifiedName~<TestName>" and treat as a test failure.

## Prevent it

- Commit a global.json pinning the SDK major, and adopt central package management. Both convert "mysterious CI drift" into explicit, reviewable diffs.

---

Classify a red build locally with the `patchrail` CLI:

```bash
pipx install patchrail
patchrail ci explain --log build.log
```
