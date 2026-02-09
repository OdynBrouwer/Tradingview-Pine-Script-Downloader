import json
r=json.load(open('analyze/jsons/failed-pubdates-retry2.json','r',encoding='utf-8'))

tot=len(r)
ok=sum(1 for it in r if it.get('published_utc'))
nulls=sum(1 for it in r if it.get('published_utc') is None)
err=sum(1 for it in r if it.get('error'))
print('retry total',tot,'published_utc found',ok,'null',nulls,'error',err)
