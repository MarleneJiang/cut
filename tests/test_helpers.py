from pathlib import Path
import importlib.util
import json, sys, tempfile, subprocess, hashlib
import numpy as np
import trimesh
skill=Path(__file__).resolve().parents[1] / 'skills' / 'blender-bambu-figure-split'
sys.path.insert(0,str(skill/'scripts'))
from heightfield import graph_above
from record_stage import archive
checks=[]
def check(name,condition):
 if not condition: raise AssertionError(name)
 checks.append(name)
def export_mesh(mesh,path): mesh.export(path)
with tempfile.TemporaryDirectory(prefix='figure-skill-test-') as folder:
 root=Path(folder)
 solid=graph_above([0,2],[0,3],np.ones((2,2)),5)
 check('heightfield closed solid has analytic volume 24 mm3',abs(solid.volume()-24)<1e-9)
 tilted=graph_above([0,2],[0,3],[[0,3],[2,5]],6)
 check('sloped heightfield analytic volume 21 mm3',abs(tilted.volume()-21)<1e-9)
 for name,args in [('grid reverse',([2,0],[0,3],[[0,0],[0,0]],5)),('wrong shape',([0,2],[0,3],[[0,0]],5)),('ceiling intersection',([0,2],[0,3],[[0,0],[0,5]],5))]:
  try: graph_above(*args)
  except ValueError: check('reject '+name,True)
  else: check('reject '+name,False)
 box=trimesh.creation.box(extents=[2,2,2]); export_mesh(box,root/'base.stl')
 moving=box.copy();moving.apply_translation([3,0,0]);export_mesh(moving,root/'moving.stl')
 config={'units':'mm','parts':{'base':'base.stl','moving':'moving.stl'},'assembly_order':[{'moving':'moving','against':['base'],'direction':[1,0,0],'distance_mm':6,'samples':25}]}
 def run(name,cfg,expected):
  manifest=root/(name+'.json');manifest.write_text(json.dumps(cfg))
  report=root/(name+'-report.json')
  result=subprocess.run([sys.executable,str(skill/'scripts/audit_parts.py'),str(manifest),'--output',str(report)],capture_output=True,text=True)
  if result.returncode!=expected: print(result.stdout,result.stderr)
  check(name,result.returncode==expected)
  return json.loads(report.read_text())
 run('collision-free withdrawal passes',config,0)
 bad=json.loads(json.dumps(config));bad['assembly_order'][0]['direction']=[-1,0,0]
 report=run('path collision is rejected even when final position is clear',bad,1)
 check('collision report includes 8 mm3 overlap',abs(report['withdrawals'][0]['max_overlap_mm3']-8)<1e-7)
 bad=json.loads(json.dumps(config));bad['assembly_order'][0]['against']=[]
 run('missing blocker rejected',bad,2)
 bad=json.loads(json.dumps(config));bad['assembly_order']=[]
 run('missing assembly sequence rejected',bad,2)
 bad=json.loads(json.dumps(config));bad['assembly_order'][0]['direction']=[0,0,0]
 run('zero direction rejected',bad,2)
 collided=box.copy();collided.apply_translation([1,0,0]);export_mesh(collided,root/'moving.stl')
 run('assembled interference rejected',config,1)
 mesh=trimesh.Trimesh(box.vertices,box.faces[:-1],process=False);export_mesh(mesh,root/'moving.stl')
 run('open mesh rejected',config,2)
 data=b'actual stage file\n';(root/'model.txt').write_bytes(data)
 spec={'stage':'01-check','title':'Test stage','record_type':'retrospective','performed_by':'automated fixture','problem':'test','decision':'preserve bytes','actions':['archive existing file'],'result':'fixture only','artifacts':[{'path':'model.txt','kind':'report','caption':'fixture bytes'}]}
 specpath=root/'spec.json';specpath.write_text(json.dumps(spec))
 dest=archive(specpath,root/'evidence');manifest=json.loads((dest/'manifest.json').read_text())
 check('archive copies exact bytes', (dest/manifest['artifacts'][0]['file']).read_bytes()==data)
 check('archive records correct SHA256',manifest['artifacts'][0]['sha256']==hashlib.sha256(data).hexdigest())
 check('archive distinguishes retrospective evidence',manifest['record_type']=='retrospective' and 'operation_time' not in manifest)
 try:archive(specpath,root/'evidence')
 except FileExistsError:check('archive refuses overwrite',True)
 else:check('archive refuses overwrite',False)
 spec['stage']='02-missing';spec['artifacts'][0]['path']='missing.blend';specpath.write_text(json.dumps(spec))
 try:archive(specpath,root/'evidence')
 except ValueError:check('archive rejects nonexistent evidence',True)
 else:check('archive rejects nonexistent evidence',False)
 check('failed archive has no completed stage',(root/'evidence'/'02-missing').exists()==False)
print(json.dumps({'passed':len(checks),'checks':checks},ensure_ascii=False,indent=2))
