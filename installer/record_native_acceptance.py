"""Record a human-reviewed native fullscreen run; never auto-fill observations."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
import release_gate as gate

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--run',required=True);p.add_argument('--observations',required=True)
p.add_argument('--recording',required=True)
args=p.parse_args();run=Path(args.run).resolve(strict=True)
context=json.loads((run/'context.json').read_text('utf-8'));gate.validate_context(context)
observations=json.loads(Path(args.observations).read_text('utf-8'))
if observations.get('binding')!=gate.binding(context):raise ValueError('Observations must quote this candidate binding')
if observations.get('evidence_class')!='native-ui' or observations.get('product')!='DeepSteam':
    raise ValueError('Native DeepSteam evidence required; browser tests cannot substitute')
if not observations.get('reviewer') or any(observations.get('steps',{}).get(s) is not True for s in gate.NATIVE_STEPS):
    raise ValueError('A reviewer must complete all native observations')
if observations.get('samples',0)<30 or not 0<=observations.get('max_scroll_drift_px',999)<=1:
    raise ValueError('Fullscreen scrolling did not satisfy stability acceptance')
record=gate.descriptor(args.recording)
if record['bytes']<1024 or Path(record['path']).suffix.lower() not in ('.mp4','.webm','.mov'):
    raise ValueError('A nonempty native recording is required')
gate.save_new(run/'native-fullscreen.json',gate.receipt(context,'native-fullscreen',passed=True,
    evidence_class='native-ui',product='DeepSteam',reviewer=observations['reviewer'],
    steps=observations['steps'],samples=observations['samples'],max_scroll_drift_px=observations['max_scroll_drift_px'],
    recording=record,observations=gate.descriptor(args.observations)))
print('Native observations recorded for this candidate only. Run release_gate.py check before promotion.')
