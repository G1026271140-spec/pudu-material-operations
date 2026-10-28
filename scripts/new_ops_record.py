#!/usr/bin/env python3
"""Create a non-overwriting change record in the current Git workspace."""
import argparse
from datetime import datetime, timezone, timedelta
from pathlib import Path
import re


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('slug', help='Short ASCII task name, e.g. shipping-date-card')
    args = parser.parse_args()
    if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', args.slug): parser.error('slug must contain lowercase words separated by hyphens')
    root = Path(__file__).resolve().parents[1]
    template = root/'docs/ops/templates/change-record.md'
    now = datetime.now(timezone(timedelta(hours=8)))
    target = root/'docs/ops/changes'/f'{now:%Y%m%d-%H%M%S}-{args.slug}.md'
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('x',encoding='utf-8') as output:
        output.write(template.read_text(encoding='utf-8').replace('{{TASK}}',args.slug).replace('{{TIME}}',now.isoformat(timespec='seconds')))
    print(target.relative_to(root))


if __name__ == '__main__': main()
