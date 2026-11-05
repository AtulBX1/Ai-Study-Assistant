# Keeping the Test Suite Fast

## What we built

The default pytest run skips tests marked `slow`. Tests that train models,
download data, use longer GPU or tensor loops, or take more than five seconds
carry that marker. The check script runs Ruff checks, checks formatting, and
then runs the fast test suite.

## Why it helps

Quick tests make it easier to check changes often. Slow tests still matter, so
they remain available when someone needs to check model training or data
downloads.

## How it works

Pytest reads `addopts` and excludes the `slow` marker by default. Run
`uv run pytest -m slow` from `backend` to select those tests. Run
`scripts/check.ps1` from the project root for the standard checks.

## Key syllabus concept

Testing an NLP model includes checking both its behavior and its measured
quality. Small tests verify expected shapes and outputs; longer training tests
check learning behavior and can be run separately.

## Viva questions

1. **What is a pytest marker?**  
   A marker labels a test so pytest can select or skip it.
2. **Why are model-training tests marked slow?**  
   They perform repeated computation and can take longer than ordinary unit
   tests.
3. **How do you run only slow tests?**  
   Run `uv run pytest -m slow` from the backend folder.
4. **Does skipping slow tests remove them?**  
   No. The tests remain in the suite and can still be selected explicitly.
5. **What does the check script verify?**  
   It runs Ruff linting, formatting checks, and the default pytest suite.
