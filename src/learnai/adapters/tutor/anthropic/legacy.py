"""SDK-free, explicitly Anthropic adaptation of historical v1 evaluation runs."""
from dataclasses import asdict
from pathlib import Path

from learnai.adapters.tutor.anthropic.usage import normalize_anthropic_usage
from learnai.adapters.tutor.observations import UsageStatus
from learnai.eval.artifacts import SavedRun, _request_record, _run_structure, load_packets


def read_run_v1(directory: Path) -> SavedRun:
    manifest, report, raw = _run_structure(directory, 1)
    records = []
    for entry in raw:
        try:
            for name in ('raw_usage', 'request', 'response'):
                if entry.get(name) is not None and not isinstance(entry[name], dict):
                    raise ValueError('invalid legacy raw observation mapping')
            usage = normalize_anthropic_usage(entry['raw_usage'], status=UsageStatus(entry['usage_status']),
                response_metadata=entry.get('response'), request_settings=entry.get('request'))
            value = dict(entry, schema_version=2, provider='anthropic', api_family='messages', usage_status=usage.status.value,
                normalized_usage={**asdict(usage), 'status': usage.status.value, 'reasons': list(usage.reasons)}, normalized_tokens=dict(usage.counts))
            records.append(_request_record(value))
        except (KeyError, TypeError) as exc:
            raise ValueError('invalid legacy request') from exc
    if len({record.request_id for record in records}) != len(records):
        raise ValueError('duplicate saved request identity')
    packets = load_packets(directory) if report.get('eligible_ids') else {}
    if not report.get('eligible_ids') and report.get('judge_packets') != {}:
        raise ValueError('invalid empty packet index')
    return SavedRun(directory, manifest, tuple(records), packets, report,
        ('Legacy v1 adaptation: provider inferred as Anthropic Messages; normalized with anthropic-messages@1. '
         'Missing request/response billing evidence remains unknown; normalization differs from v1.',))
