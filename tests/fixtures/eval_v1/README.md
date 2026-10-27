Frozen baseline v1 synthetic evaluation

Generated once through unchanged revision `40d2559` in an isolated `git archive` export before Task 3 writer changes. No keys, network, real traces or student data. `run/` is immutable; this README, recipe and checksum inventory are external to the run. Tests never regenerate it.

Exact recipe (from repository root):

```sh
git archive 40d2559 -o /tmp/learnai-task3-baseline.tar
mkdir -p /tmp/learnai-task3-baseline
tar -xf /tmp/learnai-task3-baseline.tar -C /tmp/learnai-task3-baseline
cp tests/fixtures/eval_v1/generate_fixture.py /tmp/learnai-task3-baseline/generate_fixture.py
cd /tmp/learnai-task3-baseline
env -u ANTHROPIC_API_KEY -u OPENAI_API_KEY PYTHONPATH=/tmp/learnai-task3-baseline/src:/tmp/learnai-task3-baseline /Users/adrianseguralorente/LearnAI-worktrees/plan-phase2a-tutor/.venv/bin/python generate_fixture.py
```

Writer output `/tmp/learnai-task3-fixture-output/baseline-v1-synthetic` was copied to `run/`; SHA256 of every emitted file is in `checksums.json`. Capture root `/tmp/learnai-task3-minimal-root` has no project inputs.

Expected decoding: manifest/report schema 1, run id `baseline-v1-synthetic`, selected `synthetic-case`, seed 7; one accepted packet with the synthetic turn from baseline test `packet()`, score mathematics 2/help_level 1/diagnosis 2/tone 2; request id `a`, requested model `fiction-alias`, returned `fiction-model`, normalized input 100, output 400, cache read 200, 5m cache write 300. Legacy provider inference is Anthropic; missing billing evidence remains unknown.
