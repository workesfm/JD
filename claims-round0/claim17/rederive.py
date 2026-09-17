"""Independent streaming reconstruction of the two Grambank tables.

Only the statement, raw pinned dataset and stdlib are used. No network calls.
The amended commit-pinned MD5 is used, not the superseded MD5 in the issue.
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path

EXPECTED_MD5 = '60f1ae344334037c5064ce532300fae5'
FEATURES = {'GB147', 'GB155', 'GB302'}


def digest_file(path):
    md5, sha = hashlib.md5(), hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            md5.update(chunk)
            sha.update(chunk)
    return md5.hexdigest(), sha.hexdigest()


def reconstruct(rows):
    records = {}
    all_languages = set()
    row_count = 0
    for row in rows:
        row_count += 1
        language, feature, value = row['Language_ID'], row['Parameter_ID'], row['Value']
        all_languages.add(language)
        if feature not in FEATURES:
            continue
        key = (language, feature)
        if key in records and records[key] != value:
            raise ValueError('conflicting duplicate value for a language/feature')
        records[key] = value

    def table(first):
        counts = {'00': 0, '01': 0, '10': 0, '11': 0}
        dropped = 0
        for language in all_languages:
            a, b = records.get((language, first)), records.get((language, 'GB155'))
            if a not in {'0', '1'} or b not in {'0', '1'}:
                dropped += 1
                continue
            counts[a + b] += 1
        return {'row_feature': first, 'column_feature': 'GB155', 'cells': counts,
                'n': sum(counts.values()), 'languages_excluded': dropped}
    return {'table_A': table('GB147'), 'table_B': table('GB302'),
            'audit': {'rows_read': row_count, 'languages_in_file': len(all_languages),
                      'selected_language_feature_pairs': len(records)}}


def self_test():
    def r(lang, feature, value):
        return dict(Language_ID=lang, Parameter_ID=feature, Value=value)
    rows = [r('a', 'GB147', '0'), r('a', 'GB155', '1'), r('a', 'GB302', '?'),
            r('b', 'GB147', '1'), r('b', 'GB155', '0'), r('b', 'GB302', '1'),
            r('c', 'GB147', '0'), r('c', 'GB155', '?'),
            r('d', 'GB302', '0'), r('d', 'GB155', '1'),
            r('e', 'IGNORED', '1'), r('b', 'GB147', '1')]
    actual = reconstruct(rows)
    assert actual['table_A']['cells'] == {'00': 0, '01': 1, '10': 1, '11': 0}
    assert actual['table_B']['cells'] == {'00': 0, '01': 1, '10': 1, '11': 0}
    assert actual['table_A']['languages_excluded'] == 3
    assert reconstruct(reversed(rows)) == actual
    assert reconstruct([])['table_A']['n'] == 0
    try:
        reconstruct([r('x', 'GB155', '0'), r('x', 'GB155', '1')])
    except ValueError:
        pass
    else:
        raise AssertionError('conflicting duplicate must not be silently overwritten')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data', type=Path, default=Path('/data/grambank-values.csv'))
    args = parser.parse_args()
    self_test()
    md5, sha = digest_file(args.data)
    if md5 != EXPECTED_MD5:
        raise ValueError('dataset MD5 differs from the amended commit-pinned Grambank blob')
    with args.data.open(encoding='utf-8-sig', newline='') as source:
        rows = csv.DictReader(source)
        if not {'Language_ID', 'Parameter_ID', 'Value'}.issubset(rows.fieldnames or []):
            raise ValueError('required CSV headers missing')
        result = reconstruct(rows)
    print(json.dumps({'claim': 17, 'data_md5': md5, 'data_sha256': sha,
                      'synthetic_edge_cases_passed': True, **result}, sort_keys=True, indent=2))


if __name__ == '__main__':
    main()
