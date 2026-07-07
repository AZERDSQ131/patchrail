<!-- Canonical: https://getpatchrail.com/fix/java-build-failure -->

# Java build failures — Unsupported class file major version

> Part of the **CI Failure Triage** field guide. The canonical, formatted version of this page lives at **[getpatchrail.com/fix/java-build-failure](https://getpatchrail.com/fix/java-build-failure)**.

## Log signatures

These are the literal strings to search for in the failed log:

```text
Unsupported class file major version 65
Could not determine java version
Could not resolve dependencies
cannot find symbol
BUILD FAILED
```

## What actually happened

The two most diagnostic signatures here are version-skew tells: "Unsupported class file major version" means bytecode compiled by a newer JDK is being read by an older one (major 61 = Java 17, 65 = Java 21, 69 = Java 25 — the number names the culprit); "Could not determine java version" is usually an old Gradle that can't parse a new JDK's version string. "cannot find symbol" / "package does not exist" are compile errors — but when they appear en masse right after dependency lines, the real cause is upstream: a dependency that failed to resolve ("Could not resolve dependencies"), so every import from it "doesn't exist." "No tests found for given includes" means your test filter matched nothing — often a renamed test class with a stale CI filter.

## Fix it

1. Find the first "Could not resolve" line. If present, fix resolution first — ignore the hundreds of "cannot find symbol" errors below it; they're shadows.
2. Version skew: align JDK across toolchain — java -version in CI vs sourceCompatibility/targetCompatibility/toolchain block. For Gradle, check the Gradle-vs-JDK compatibility matrix before bumping either.
3. Genuine COMPILATION ERROR with resolution healthy: ordinary code fix at the first reported file:line.
4. No tests found for given includes: fix the include filter or the test class naming; this fails builds on most configs and is pure configuration.
5. Rerun the single failing task/goal, not the whole lifecycle: ./gradlew :module:test / mvn -pl module test.

## Prevent it

- Use Gradle/Maven toolchains to declare the JDK in the build itself, so the build selects (or fails fast on) the right JDK rather than silently using whatever CI has.

---

Classify a red build locally with the `patchrail` CLI:

```bash
pipx install patchrail
patchrail ci explain --log build.log
```
