"""Compare Python files between two git revisions at the AST level (docstrings stripped)."""
import ast, subprocess, sys
A, B = sys.argv[1], sys.argv[2]
files = subprocess.run(["git","ls-tree","-r","--name-only",B],capture_output=True,text=True).stdout.split()
def norm(src):
    t = ast.parse(src)
    for n in ast.walk(t):
        body = getattr(n, "body", None)
        if isinstance(body, list) and body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0],"value",None), ast.Constant) and isinstance(body[0].value.value,str):
            n.body = body[1:] or [ast.Pass()]
        if isinstance(body, list):
            n.body = [s for s in n.body if not (isinstance(s, ast.Expr) and isinstance(getattr(s,"value",None), ast.Constant) and isinstance(s.value.value,str))] or [ast.Pass()]
    return ast.dump(t)
for f in files:
    if not f.endswith(".py"): continue
    a = subprocess.run(["git","show",f"{A}:{f}"],capture_output=True,text=True)
    b = subprocess.run(["git","show",f"{B}:{f}"],capture_output=True,text=True)
    if a.returncode: print("NEW", f); continue
    same = norm(a.stdout)==norm(b.stdout)
    if a.stdout!=b.stdout: print("AST_SAME" if same else "AST_DIFF", f)
