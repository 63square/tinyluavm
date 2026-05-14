# `split-deploy` example

A complete, runnable example of shipping tinyvm as three separate Luau
modules:

1. `tinyvm.luau` — the 2485-byte micro-VM.
2. `macrovm-ast.luau` — the pre-decoded macro-VM AST (`return {K, F}`).
3. `user-ast.luau` — the pre-decoded user program (`return {K, F}`).

The launcher `require()`s all three, combines the two ASTs into the
micro-VM's `inputData` argument, and calls `micro(inputData, getfenv())`.

This is the layout you'd use when:

* the Luau source you ship matters (`src/tinyvm.luau` is the only
  Luau-source file the user sees), and
* you can deliver the AST modules through a separate channel — a
  Roblox `ModuleScript`, a `HttpService:GetAsync` response, an asset,
  or a generated string literal pasted into your build pipeline.


## Layout

```
examples/split-deploy/
├── README.md              you are here
├── build_and_run.py       driver: compile + predecode + stage + invoke luau
├── launcher.luau          ★ the launcher: this is the file you'd write
├── user.luau              a sample user program
└── staged/                ↑ assembled by build_and_run.py, gitignored
    ├── tinyvm.luau            copy of src/tinyvm.luau
    ├── macrovm-ast.luau       copy of build/macrovm-ast.luau
    ├── user-ast.luau          user.luau predecoded to {K, F}
    └── launcher.luau          copy of ../launcher.luau
```

The `staged/` subdirectory mimics the structure a real consumer would
end up with: the launcher and the three modules it `require()`s all
sitting next to each other. The driver assembles this fresh on every
run so you can re-run the example without worrying about leftover
state.


## Run it

From the project root:

```bash
python examples/split-deploy/build_and_run.py
```

If you haven't built the macro-VM AST yet (`build/macrovm-ast.luau`),
the driver builds it for you on the first run. Subsequent runs reuse
it.

Expected output:

```
[split-deploy] staged tinyvm.luau (2485 bytes)
[split-deploy] staged macrovm-ast.luau (13816 bytes)
[split-deploy] compiled user.luau (1489 bytes of bytecode)
[split-deploy] predecoded user.luau -> user-ast.luau (3916 bytes)
[split-deploy] staged launcher.luau
[split-deploy] invoking luau on staged/launcher.luau
============================================================
hello from tinyvm-split-deploy-example v1.0
first three ids: 101, 102, 103
stats: sum=44 count=11 mean=4
basket: apple:0.5, banana:0.25, cherry:1.1, durian:7
basket total: 8.85
a = Vec(3, 4), |a| = 5
a + b = Vec(4, 6)
10 / 2 ok=true result=5
10 / 0 ok=false err=division by zero
countdown: 5 4 3 2 1
user.luau done
============================================================
[split-deploy] done
```


## What each file does

### `launcher.luau` (the interesting part)

This is what you'd actually write in a real project. It:

1. `require()`s the three Luau modules:
   * `./tinyvm`      — the 2485-byte micro-VM, a function value.
   * `./macrovm-ast` — a `{K, F}` table for the macro-VM.
   * `./user-ast`    — a `{K, F}` table for the user program.
2. Optionally injects host globals (`hostInfo = ...`).
3. Calls `micro({m = mvmAst, u = userAst}, getfenv())`.

The whole launcher is ~25 lines. No shadow env construction, no
helper-function wiring, no chunk-name plumbing — the micro-VM
handles arithmetic, error propagation, and stdlib lookup directly
through the env table you pass in.

### `user.luau` (the user program)

A small but non-trivial Luau program that exercises closures with
upvalues, varargs, multi-return, generic-for over a hash table, a
metatable with `__index` / `__add` / `__tostring`, `pcall` + `assert`,
string interpolation, compound assignment, numeric-for with a
negative step, and access to a host-provided global (`hostInfo`,
which the launcher injects via the env).

If you can break any of this, please [open an issue](../../../../issues).

### `build_and_run.py` (the driver)

A ~100-line Python script that mimics what your real build pipeline
would do:

* Make sure `build/macrovm-ast.luau` exists, running `tools/build.py`
  if not.
* Compile `user.luau` to a `.bin` via `tools/compiler.py`.
* Predecode the `.bin` into a Luau module `user-ast.luau` returning
  `{K, F}` via `tools/predecode.py` (without `--for-micro` — the
  macro-VM consumes the user AST at runtime, so we keep the
  macro-VM-friendly atom set).
* Copy `src/tinyvm.luau`, `build/macrovm-ast.luau`, the
  predecoded `user-ast.luau`, and the launcher into `staged/`.
* Invoke `luau staged/launcher.luau`.

Nothing about this is specific to the example — you'd do roughly the
same shape of work in a Roblox build pipeline that uploads each of
the four files as a separate `ModuleScript`.


## Customizing

* **Restricting what the user sees.** Pass a curated table as the
  second argument instead of `getfenv()`. For example:
  ```lua
  local sandbox = {print=print, math=math}
  micro({m=mvmAst, u=userAst}, sandbox)
  ```
* **Injecting host APIs.** Write to globals before the call;
  `getfenv()` will pick them up:
  ```lua
  hostInfo = {appName = "my-game"}
  myGameAPI = {spawn = function(x, y) ... end}
  micro({m=mvmAst, u=userAst}, getfenv())
  ```
* **Different transport for the ASTs.** The launcher uses `require()`,
  but the modules can come from anywhere: a Roblox `ModuleScript`,
  generated string literals, etc. Replace `require("./macrovm-ast")`
  with whatever loader returns the `{K, F}` table.
* **More user programs.** Drop another `.luau` file in this folder
  and tweak `build_and_run.py` to compile and predecode that one too.

See the siblings [`json-deploy/`](../json-deploy/) (same idea but
with a single combined JSON document as the wire format) and
[`http-deploy/`](../http-deploy/) (same JSON payload, fetched over
HTTP at runtime).
