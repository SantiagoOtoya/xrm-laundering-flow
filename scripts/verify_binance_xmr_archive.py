"""Compare the supplied monthly CSVs with official Binance ZIPs and checksums."""
import argparse
import concurrent.futures
import csv
import datetime as dt
import hashlib
import io
import json
import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STORE = ROOT / 'data/raw/binance/official_monthly_zips'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def fetch(url, path):
    if path.exists():
        return path.read_bytes(), None
    response = subprocess.run(['curl','--fail','--silent','--show-error','--max-time','30',
                               '--max-filesize','6000000',url],capture_output=True)
    if response.returncode:
        raise ValueError('Official download failed: '+url+' '+response.stderr.decode(errors='replace')[:200])
    path.write_bytes(response.stdout)
    return response.stdout, dt.datetime.now(dt.timezone.utc).isoformat()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive',type=Path)
    args=parser.parse_args()
    STORE.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(args.archive) as supplied:
        rows=list(csv.DictReader(io.StringIO(supplied.read('SOURCES.csv').decode())))
        supplied_hashes={r['csv']:sha(supplied.read('monthly_csv/'+r['csv'])) for r in rows}
    def verify(row):
        name=row['csv'].replace('.csv','.zip')
        url='https://data.binance.vision/data/spot/monthly/klines/XMRBTC/1m/'+name
        if url != row['source_zip_url'] or '/' in name or not name.startswith('XMRBTC-1m-'):
            raise ValueError('Unexpected supplied source name/URL')
        try:
            checksum, at1=fetch(url+'.CHECKSUM',STORE/(name+'.CHECKSUM'))
            raw, at2=fetch(url,STORE/name)
            official_hash=checksum.decode().split()[0]
            if sha(raw) != official_hash or len(official_hash)!=64:
                raise ValueError('Official ZIP checksum mismatch')
            with zipfile.ZipFile(io.BytesIO(raw)) as z:
                if z.namelist() != [row['csv']]:
                    raise ValueError('Unexpected official ZIP members')
                csv_hash=sha(z.read(row['csv']))
            matches=csv_hash==supplied_hashes[row['csv']]
            result=dict(csv=row['csv'],source_url=url,official_zip_sha256=sha(raw),
                official_csv_sha256=csv_hash,supplied_csv_sha256=supplied_hashes[row['csv']],
                declared_zip_hash_matches=sha(raw)==row['downloaded_zip_sha256'],
                exact_csv_match=matches, status='verified' if matches else 'csv_differs',
                fetched_at_utc=at2 or at1)
        except (ValueError,KeyError,zipfile.BadZipFile) as exc:
            result=dict(csv=row['csv'],source_url=url,status='verification_failed',error=str(exc))
        print(json.dumps({'csv':row['csv'],'status':result['status']}),flush=True)
        return result
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        results=list(pool.map(verify,rows))
    output=ROOT/'data/raw/binance/official_verification.json'
    previous=json.loads(output.read_text()) if output.exists() else None
    if previous:
        old={r['csv']:r for r in previous['monthly']}
        for r in results:
            if r.get('fetched_at_utc') is None and r['csv'] in old:
                r['fetched_at_utc']=old[r['csv']].get('fetched_at_utc')
    report=dict(supplied_archive_sha256=sha(args.archive.read_bytes()),
                verified_files=sum(r['status']=='verified' for r in results),monthly=results)
    output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'verified_files':report['verified_files'],'total_files':len(rows)}))
    if report['verified_files']!=len(rows):
        raise SystemExit(1)


if __name__=='__main__':
    main()
