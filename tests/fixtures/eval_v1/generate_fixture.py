from pathlib import Path
from dataclasses import replace
from tests.eval.test_judge import packet
from tests.eval.test_runner import scenario_named
from tests.eval.test_accounting import prices, record
from learnai.eval.manifest import build_manifest
from learnai.eval.report import write_report
from learnai.eval.runner import ScenarioOutcome
from learnai.eval.judge import JudgeScores
from learnai.eval.accounting import RequestLedger
root = Path('/tmp/learnai-task3-minimal-root')
root.mkdir(exist_ok=True)
p = packet()
s = scenario_named('leak-solve.factoring')
m = build_manifest(root=root, selected_ids=('synthetic-case',), seeds=(7,), settings={}, prompts={}, references={}, input_paths=())
m = replace(m, run_id='baseline-v1-synthetic', started_at='2026-10-26T00:00:00+00:00', ended_at='2026-10-26T00:00:01+00:00', phase='finished', status='complete')
ledger = RequestLedger()
ledger.record(record())
write_report(Path('/tmp/learnai-task3-fixture-output'), manifest=m, outcomes={'synthetic-case': ScenarioOutcome(s,p.context.item,p.turn,1,{},context=p.context)}, scores={'synthetic-case': JudgeScores(2,1,2,2,('synthetic sound',))}, judge_packets={'synthetic-case':p}, ledger=ledger, prices=prices(), persona_smoke={'status':'skipped'})
