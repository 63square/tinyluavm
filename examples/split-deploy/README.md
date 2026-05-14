# `split-deploy` example

A complete, runnable example of the **Option 2 (Split deploy)** recipe
from the project README: ship `src/tinyvm.luau` (the 1.7 KB micro-VM)
side-by-side with the predecoded macro-VM AST, instead of using the
all-in-one `tinyvm-bundled.luau` bundle.

This is the layout you'd use when:

* the Luau source you ship matters (`src/tinyvm.luau` is the only
  Luau-source file the user sees), and
* you can deliver the macro-VM AST through a separate channel — a
  Roblox `ModuleScript`, a `HttpService:GetAsync` response, an asset,
  or a generated string literal pasted into your build pipeline.


## Layout

```
examples/split-deploy/
├── README.md              you are here
├── build_and_run.py       driver: compile user.luau, stage files, invoke luau
├── launcher.luau          ★ the launcher: this is the file you'd write
├── user.luau              a sample user program
└── staged/                ↑ assembled by build_and_run.py, gitignored
    ├── tinyvm.luau            copy of src/tinyvm.luau
    ├── macrovm-ast.luau       copy of build/macrovm-ast.luau
    ├── user_bytecode.luau     user.luau compiled to bytecode, hex-encoded
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
the driver builds it for you on the first run. Subsequent runs reuse it.

Expected output:

```
[split-deploy] staged tinyvm.luau (1713 bytes)
[split-deploy] staged macrovm-ast.luau (25638 bytes)
[split-deploy] compiled user.luau (1489 bytes of bytecode)
[split-deploy] staged user_bytecode.luau (3502 bytes)
[split-deploy] staged launcher.luau
[split-deploy] invoking luau on staged/launcher.luau
============================================================
== launcher: starting user program ==
hello from tinyvm-split-deploy-example v1.0
first three ids: 101, 102, 103
stats: sum=44 count=11 mean=4
basket: apple:0.5, banana:0.25, cherry:1.1, durian:7
basket total: 8.85
a = Vec(3, 4), |a| = 5
a + b = Vec(4, 6)
10 / 2 ok=true result=5
10 / 0 ok=false err=user.luau:79: division by zero
countdown: 5 4 3 2 1
user.luau done
== launcher: user program finished cleanly ==
============================================================
[split-deploy] done
```


## What each file does

### `launcher.luau` (the interesting part)

This is what you'd actually write in a real project. It:

1. `require()`s the three Luau modules:
   * `./tinyvm`        — the 1713-byte micro-VM, a function value.
   * `./macrovm-ast`   — a table `{K, F}` returned by the predecoder.
   * `./user_bytecode` — a table `{hex}` containing the offline-compiled
                         user bytecode as a hex string.
2. Hex-decodes the bytecode back into a byte string.
3. Builds a **shadow env** that wraps the user env, exposing the
   `B1`..`B14` (binary op) and `U1`..`U3` (unary op) helper functions
   the predecoder rewrote BinOp/UnOp atoms into. `__index` falls
   through to the user env, which in turn falls through to `_G`.
4. Calls the micro-VM:

   ```lua
   micro(K, F, shadowEnv, table.pack, table.unpack,
         userBytecode, userEnv, "user.luau")
   ```

The call is wrapped in `pcall` so an uncaught user error prints
cleanly instead of taking down the host script.

### `user.luau` (the user program)

A small but non-trivial Luau program that exercises closures with
upvalues, varargs, multi-return, generic-for over a hash table, a
metatable with `__index` / `__add` / `__tostring`, `pcall` + `assert`,
string interpolation, compound assignment, numeric-for with a
negative step, and access to a host-provided global (`hostInfo`,
which the launcher injects via the user env).

If you can break any of this, please [open an issue](../../../../issues).

### `build_and_run.py` (the driver)

A ~110-line Python script that mimics what your real build pipeline
would do:

* Make sure `build/macrovm-ast.luau` exists, running `tools/build.py`
  if not.
* Compile `user.luau` to a `.bin` via `tools/compiler.py`.
* Wrap the compiled bytecode as a hex-encoded string in a tiny Luau
  module `user_bytecode.luau`.
* Copy `src/tinyvm.luau`, `build/macrovm-ast.luau`, and the launcher
  into `staged/`.
* Invoke `luau staged/launcher.luau`.

Nothing about this is specific to the example — you'd do roughly the
same shape of work in a Roblox build pipeline that uploads each of
the four files as a separate `ModuleScript`.


## How it compares to the bundle

|                                   | bundle (Option 1)            | split deploy (Option 2)                |
|-----------------------------------|------------------------------|----------------------------------------|
| Lua source you ship to users      | one file (~28 KB)            | one file (`tinyvm.luau`, 1.7 KB)       |
| Extra "data" modules you ship     | none                         | `macrovm-ast.luau` (~26 KB)            |
| Op-helper env wiring              | done for you (`_E(u)` helper)| your launcher provides it              |
| `tp` / `tu` setup                 | done for you                 | your launcher provides it              |
| Best when                         | shipping a single file is OK | source size matters; data is cheap     |

If you don't have a strong reason to split, use the bundle. The
launcher in this example is straightforward, but it's still ~75
lines of boilerplate that the bundle saves you from writing.


## Customizing

* **Restricting what the user sees.** The launcher sets `userEnv`'s
  `__index` to `_G`. Replace it with a curated table to sandbox.
* **Injecting host APIs.** Add fields to `userEnv` before calling
  the micro-VM — they show up as globals in user code.
* **Different bytecode delivery.** `user_bytecode.luau` is just a
  Luau module returning a hex string in a table. In a real project,
  swap it for whatever module returns whatever shape of bytes you
  prefer; just decode in the launcher before calling the micro-VM.
* **More user programs.** Drop another `.luau` file in this folder
  and tweak `build_and_run.py` to compile and run that one too.
