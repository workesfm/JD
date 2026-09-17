"""Independent reconstruction of PHOIBLE claim 16, from CSV rows only.

No network and no third-party modules. Target counts are not used by the
calculation. The small synthetic self-test covers the statement's edge cases.
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path

EXPECTED_MD5 = '866d36bc83ab21bdb5837ffa63dc5993'
REQUIRED = {'InventoryID', 'Glottocode', 'Phoneme', 'Marginal', 'raisedLarynxEjective'}


def digest_file(path):
    md5, sha = hashlib.md5(), hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            md5.update(chunk)
            sha.update(chunk)
    return md5.hexdigest(), sha.hexdigest()


def count_table(inventories):
    cells = {'ejectives_and_ng': 0, 'ejectives_without_ng': 0,
             'ng_without_ejectives': 0, 'neither': 0}
    for _, ejective, ng in inventories:
        key = ('ejectives_and_ng' if ng else 'ejectives_without_ng') if ejective else (
            'ng_without_ejectives' if ng else 'neither')
        cells[key] += 1
    return {**cells, 'n': sum(cells.values())}


def reconstruct(rows):
    inventories = {}
    row_count = marginal_count = 0
    for row in rows:
        row_count += 1
        ident = int(row['InventoryID'])
        language = row['Glottocode']
        if ident not in inventories:
            # Preserve inventory membership even if every phoneme is marginal.
            inventories[ident] = [language, False, False]
        record = inventories[ident]
        if record[0] != language:
            raise ValueError('one InventoryID has conflicting Glottocodes')
        if row['Marginal'] == 'TRUE':
            marginal_count += 1
            continue
        record[1] |= row['raisedLarynxEjective'] == '+'
        record[2] |= row['Phoneme'] == '\u014b'

    chosen = {}
    missing_language = 0
    for ident, record in inventories.items():
        language = record[0]
        if language == 'NA':
            missing_language += 1
            continue
        if language not in chosen or ident < chosen[language]:
            chosen[language] = ident
    return {'table_A': count_table(inventories.values()),
            'table_B': count_table(inventories[ident] for ident in chosen.values()),
            'audit': {'rows_read': row_count, 'marginal_rows_discarded': marginal_count,
                      'inventories': len(inventories), 'NA_glottocode_inventories': missing_language,
                      'selected_languages': len(chosen)}}


def self_test():
    def r(i, lang, phone, marginal='FALSE', ejective='-'):
        return dict(InventoryID=str(i), Glottocode=lang, Phoneme=phone,
                    Marginal=marginal, raisedLarynxEjective=ejective)
    rows = [r(10, 'same', '\u014b', ejective='+'), r(2, 'same', '\u014b\u02d0'),
            r(3, 'second', '\u014b'), r(3, 'second', 't', 'TRUE', '+'),
            r(4, 'NA', 'k', ejective='+'), r(5, 'third', '\u014b', 'TRUE', '+')]
    actual = reconstruct(rows)
    assert actual['table_A'] == {'ejectives_and_ng': 1, 'ejectives_without_ng': 1,
                                 'ng_without_ejectives': 1, 'neither': 2, 'n': 5}
    assert actual['table_B'] == {'ejectives_and_ng': 0, 'ejectives_without_ng': 0,
                                 'ng_without_ejectives': 1, 'neither': 2, 'n': 3}
    assert reconstruct(reversed(rows)) == actual
    assert reconstruct([])['table_A']['n'] == 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data', type=Path, default=Path('/data/phoible.csv'))
    args = parser.parse_args()
    self_test()
    md5, sha = digest_file(args.data)
    if md5 != EXPECTED_MD5:
        raise ValueError('dataset MD5 does not match the statement-pinned PHOIBLE file')
    with args.data.open(encoding='utf-8-sig', newline='') as source:
        rows = csv.DictReader(source)
        if not REQUIRED.issubset(rows.fieldnames or []):
            raise ValueError('required CSV headers missing')
        result = reconstruct(rows)
    print(json.dumps({'claim': 16, 'data_md5': md5, 'data_sha256': sha,
                      'synthetic_edge_cases_passed': True, **result}, sort_keys=True, indent=2))


if __name__ == '__main__':
    main()
