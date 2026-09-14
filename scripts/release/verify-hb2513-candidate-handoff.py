"""Reproduce the 2026-09-14 bulk candidate delivery proof.

Reads every stored record, compares it with the committed producer artifact,
checks document counts, executes three fund queries and checks live refusal.
This is a fixed-snapshot operator check, not a general recall evaluation.
The only output file is b-verification.json in the supplied evidence directory.
"""
import argparse,gzip,hashlib,json,math,urllib.request,urllib.error
from pathlib import Path
from decimal import Decimal
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--evidence-root',type=Path,required=True)
parser.add_argument('--api',default='http://127.0.0.1:28086')
parser.add_argument('--qdrant',default='http://127.0.0.1:16333')
args=parser.parse_args()
ROOT=args.evidence_root
REPO=Path(__file__).resolve().parents[2]
source=gzip.decompress((REPO/'tests/fixtures/statecivics-hb2513-bulk-durable.c49d7105.jsonl.gz').read_bytes())
assert hashlib.sha256(source).hexdigest()=='5155056a4b2d411896787ff6e681d90a8cd58655cf3ddf6805849ca9dccc791b'
assert (ROOT/'hb2513-bulk-candidates.jsonl').read_bytes()==source
COLLECTION='svs_biz_ks_state_civics_statecivics_candidates_openai_small_v1'
HEADERS={'Content-Type':'application/json','X-SVS-Tenant-Id':'ten_ks_state_civics','X-SVS-Business-Instance-Id':'biz_ks_state_civics','X-SVS-Roles':'owner,admin'}
def req(base,path,data=None,headers=None):
 request=urllib.request.Request(base+path,data=None if data is None else json.dumps(data).encode(),headers=headers or {'Content-Type':'application/json'})
 with urllib.request.urlopen(request,timeout=180) as r:return json.load(r)
q=args.qdrant.rstrip('/')
a=args.api.rstrip('/')
expected_records=[json.loads(l) for l in source.decode().splitlines()]
expected={(r['entity_type'],r['entity_logical_id']):r for r in expected_records}
assert len(expected)==2588
stored={};offset=None;first_id=None
while True:
 data={'limit':200,'with_payload':True,'with_vector':False}
 if offset is not None:data['offset']=offset
 result=req(q,'/collections/'+COLLECTION+'/points/scroll',data)['result']
 for point in result['points']:
  first_id=first_id or point['id'];r=point['payload']['entity_record'];key=(r['entity_type'],r['entity_logical_id'])
  assert key not in stored
  assert r==expected[key], 'stored record differs from source artifact'
  assert point['payload']['entity_path']=='candidate'
  stored[key]=r
 offset=result['next_page_offset']
 if offset is None:break
assert stored==expected
vector=req(q,'/collections/'+COLLECTION+'/points',{'ids':[first_id],'with_vector':True,'with_payload':False})['result'][0]['vector']
assert len(vector)==1536 and any(vector) and all(math.isfinite(v) for v in vector)
before=json.loads((ROOT/'b-before-collections.json').read_text())
after={name:req(q,'/collections/'+name)['result']['points_count'] for name in before}
assert after[COLLECTION]==2588
assert all(after[n]==before[n] for n in before if n!=COLLECTION)
queries=[
 ('PKU treatment appropriation fiscal year 2027','PKU treatment (264-00-1000-1710)','stated','199274'),
 ('Sexually violent predator expense fund appropriation fiscal year 2027','Sexually violent predator expense fund (082-00-2379-2310)','no_limit',None),
 ('Nurse fair treatment and recovery fund appropriation fiscal year 2027','Nurse fair treatment and recovery fund','no_limit',None),
]
query_receipts=[]
for query,prefix,kind,amount in queries:
 result=req(a,'/api/v1/statecivics/entities/candidate/search',{'query':query,'limit':5},HEADERS)
 matches=[(i,h) for i,h in enumerate(result['results'],1) if h['record']['entity_type']=='appropriation_action' and h['record']['description']['text'].startswith(prefix) and h['record']['entity']['period']['end']=='2027-06-30']
 assert matches,(query,result)
 rank,hit=matches[0];r=hit['record'];entity=r['entity'];assert r==expected[(r['entity_type'],r['entity_logical_id'])]
 assert entity['amount_kind']==kind
 if amount is not None:assert Decimal(entity['amount']['value'])==Decimal(amount)
 query_receipts.append({'query':query,'rank':rank,'score':hit['score'],'record':r})
part=json.loads((ROOT/'b-partition.json').read_text())['parts'][0]
body=(ROOT/'b-parts'/part['name']).read_text()
try:req(a,'/api/v1/statecivics/entities/ingest',{'manifest':body,'manifest_sha256':part['sha256'],'path':'live','apply':True},HEADERS)
except urllib.error.HTTPError as e:
 failure=json.loads(e.read());assert e.code==422 and failure['detail']['error']=='CandidateRecordRefused'
else:raise AssertionError('live path accepted candidates')
receipt={'source_manifest_sha256':hashlib.sha256((ROOT/'hb2513-bulk-candidates.jsonl').read_bytes()).hexdigest(),
         'records_read_back_exactly':len(stored),'sample_vector_dimensions':len(vector),'collections_before':before,'collections_after':after,
         'live_path_refusal':failure,'queries':query_receipts}
(ROOT/'b-verification.json').write_text(json.dumps(receipt,indent=2,sort_keys=True)+'\n')
print(json.dumps({k:v for k,v in receipt.items() if k not in ('queries','live_path_refusal')},indent=2))
print(json.dumps([{'query':r['query'],'rank':r['rank'],'score':r['score'],'amount_kind':r['record']['entity']['amount_kind']} for r in query_receipts],indent=2))
