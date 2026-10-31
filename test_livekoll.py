import ast
from pathlib import Path
p=Path(__file__).resolve().parents[1]/'pages'/'1_Livekoll.py'
source=p.read_text()
mod=ast.parse(source)
assert any(isinstance(n,ast.FunctionDef) and n.name=='calculate' for n in mod.body)
assert any(isinstance(n,ast.FunctionDef) and n.name=='read_ticket' for n in mod.body)
assert any(isinstance(n,ast.FunctionDef) and n.name=='read_events' for n in mod.body)
print('PASS: Python syntax and expected functions')
