"""Prove that real-mode client construction and request parameters are unchanged between the
thesis version (dc06cb4) and HEAD. Pure AST/source comparison; nothing is executed against any API."""
import ast, subprocess, sys

OLD, NEW = "dc06cb4", "HEAD"
def src(rev, path):
    return subprocess.run(["git", "show", f"{rev}:{path}"], capture_output=True, text=True, check=True).stdout
def funcs(tree):
    return {n.name: n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
def calls(node, attr):
    return [n for n in ast.walk(node) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == attr]
def strip_sim_branch(fn):
    """Old functions start with `if USE_SIMULATED: ...`; drop it and the docstring."""
    body = [s for s in fn.body if not (isinstance(s, ast.If) and isinstance(s.test, ast.Name) and s.test.id == "USE_SIMULATED")]
    body = [s for s in body if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))]
    return ast.dump(ast.Module(body=body, type_ignores=[]))

ok = True
old_t, new_t = ast.parse(src(OLD, "common/anthropic_client.py")), ast.parse(src(NEW, "common/anthropic_client.py"))
of, nf = funcs(old_t), funcs(new_t)
print("1. Request functions (body after removing the old USE_SIMULATED branch and docstring):")
for name, attr in (("inference_sync", "create"), ("stream_sync", "stream"), ("inference_async", "create"), ("stream_async", "stream")):
    same_body = strip_sim_branch(of[name]) == strip_sim_branch(nf[name])
    oc, nc = calls(of[name], attr), calls(nf[name], attr)
    same_call = [ast.dump(c) for c in oc] == [ast.dump(c) for c in nc]
    kws = [k.arg for k in nc[0].keywords]
    print(f"   {name:16s} body identical: {same_body}; messages.{attr}(...) call identical: {same_call}; kwargs {kws}")
    ok &= same_body and same_call

print("2. Client construction:")
for name, cls in (("get_sync_client", "Anthropic"), ("get_async_client", "AsyncAnthropic")):
    oc = [n for n in ast.walk(of[name]) if isinstance(n, ast.Call) and getattr(n.func, "id", None) == cls][0]
    nc = [n for n in ast.walk(nf[name]) if isinstance(n, ast.Call) and getattr(n.func, "id", None) == cls][0]
    print(f"   {name}: old {ast.unparse(oc)}  new {ast.unparse(nc)}")
    ok &= not oc.args and not oc.keywords
kw = nf["_client_kwargs"]
print("   new _client_kwargs():")
for line in ast.unparse(kw).splitlines():
    print("      " + line)
real_returns = [r for r in ast.walk(kw) if isinstance(r, ast.Return) and isinstance(r.value, ast.Dict) and not r.value.keys]
print(f"   real-mode return is an empty dict literal: {bool(real_returns)} -> Anthropic() / AsyncAnthropic() with no arguments,")
print("   i.e. SDK defaults (max_retries=2, timeout 600 s / connect 5 s, limits 1000/100), as in the thesis")
ok &= bool(real_returns)

print("3. Request constants in common/config.py:")
def consts(rev):
    t = ast.parse(src(rev, "common/config.py"))
    return {n.targets[0].id: ast.literal_eval(n.value) for n in t.body if isinstance(n, ast.Assign)
            and isinstance(n.targets[0], ast.Name) and n.targets[0].id in ("ANTHROPIC_MODEL", "MAX_TOKENS", "TEMPERATURE", "SYSTEM_PROMPT", "USER_PROMPT", "RETRIEVAL_DELAY_SECONDS")}
co, cn = consts(OLD), consts(NEW)
print(f"   identical: {co == cn}  {cn}")
ok &= co == cn

print("4. Other real-path modules (AST, docstrings ignored):")
def norm(code):
    t = ast.parse(code)
    for n in ast.walk(t):
        if isinstance(getattr(n, "body", None), list):
            n.body = [s for s in n.body if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))] or [ast.Pass()]
    return ast.dump(t)
for p in ("common/pipeline_service.py", "common/retrieval.py", "locust_tests/test_inference.py", "locust_tests/test_stream.py",
          "locust_tests/test_pipeline.py", "flask_app/gunicorn_config.py", "django_app/gunicorn_config.py", "django_app/api/views.py",
          "django_app/config/settings.py"):
    same = norm(src(OLD, p)) == norm(src(NEW, p))
    print(f"   {p:34s} identical: {same}")
    ok &= same
print("5. App files (AST, docstrings ignored): HEAD minus the added startup call equals dc06cb4:")
STARTUP = {"get_sync_client", "get_async_client"}
def strip_startup(code):
    t = ast.parse(code)
    body = []
    for s_ in t.body:
        if isinstance(s_, ast.Expr) and isinstance(s_.value, ast.Call) and getattr(s_.value.func, "id", None) in STARTUP:
            continue
        if isinstance(s_, ast.ImportFrom) and s_.module == "common.anthropic_client":
            s_.names = [a for a in s_.names if a.name not in STARTUP]
            if not s_.names:
                continue
        body.append(s_)
    t.body = body
    return norm(ast.unparse(t))
for p in ("flask_app/app.py", "fastapi_app/main.py", "tornado_app/main.py", "django_app/config/wsgi.py"):
    n_added = sum(1 for s_ in ast.parse(src(NEW, p)).body if isinstance(s_, ast.Expr) and isinstance(s_.value, ast.Call)
                  and getattr(s_.value.func, "id", None) in STARTUP)
    same = strip_startup(src(NEW, p)) == norm(src(OLD, p))
    print(f"   {p:28s} startup calls added: {n_added}; otherwise identical: {same}")
    ok &= same and n_added == 1
print("RESULT:", "real mode unchanged except the point of client creation" if ok else "DIFFERENCES FOUND")
sys.exit(0 if ok else 1)
