# tinyvm

**A Luau interpreter for Luau, in 1955 bytes of Luau source.**

`tinyvm` is a two-stage Luau-in-Luau interpreter. The thing that lives in
your project is a 1.9 KB micro-VM (`src/tinyvm.luau`). It expects a
caller-supplied "macro-VM" — the full feature-complete interpreter,
pre-decoded at build time into pure-data `(K, F)` tables — and then runs
your user code on top of that macro-VM.

Every input to the micro-VM is a plain Lua value (number, string, bool,
nil, table). There are no userdata, no function literals, no opaque
blobs. That means the macro-VM AST round-trips losslessly through JSON,
and so does the user program if you predecode it too.

```
   ┌──────────────────────────────────────────────────────────────────┐
   │ src/tinyvm.luau   (1955 bytes — this is what ships)              │
   │   interprets → macro-VM AST  (pre-decoded from src/macrovm.luau) │
   │                  interprets → user code (bytes or pre-decoded)   │
   └──────────────────────────────────────────────────────────────────┘
```

The trick: the macro-VM AST and the op-helper env both come from the
*caller*, so they don't count against `tinyvm`. The micro-VM only has to
handle the small subset of Luau features the macro-VM itself uses — and
all of those have been further reduced by build-time atom rewrites that
fold opcodes the micro-VM would otherwise need to dispatch.


## What you get

* **103 internal tests pass** (35 core + 35 edge cases + 33 type-stripping).
* **All example programs pass** (closures, coroutines, fibonacci,
  hello, metatables) under both the all-in-one bundle and the all-JSON
  deployment path.
* **Roblox-compatible**. No `loadstring`, no `load`, no `debug.*`. Just
  `require`, `setmetatable`, basic stdlib.
* **Every Luau feature** the macro-VM exposes: closures, multi-return,
  varargs, metatables, `__call`/`__index`/`__namecall`/`__iter`, `pcall`,
  coroutines, generic-for, numeric-for (with all Luau corner cases),
  compound assignment, string interpolation, `if`-expressions, `continue`,
  type annotations (parsed and discarded). The micro-VM doesn't need to
  implement these directly — the macro-VM does, and the micro-VM just
  needs to interpret the macro-VM.
* **JSON-encodable input plane**. The macro-VM AST and (optionally) the
  user program AST are both pure data — JSON serializable, diffable,
  hashable, transformable with `jq`.


## Layout

    src/
      tinyvm.luau          micro-VM — the 1955-byte interpreter
      macrovm.luau         macro-VM source (Luau) — readable reference;
                           compiled and pre-decoded at build time
    tools/
      compiler.py          offline Luau → bytecode compiler
      predecode.py         compiles a .bin into a Lua `return {K, F}`
                           module (or JSON, with --json); applies
                           atom-shrinking rewrites if --for-micro
      build.py             builds build/macrovm.bin + macrovm-ast.luau +
                           the self-contained bundle
      tinyvm.py            CLI wrapper for compile + run
      test.py              test runner (strict: silent passes fail)
    build/                 generated artifacts (after `python tools/build.py`)
      macrovm.bin          compiled macro-VM bytecode (reference only)
      macrovm-ast.luau     pre-decoded macro-VM as `return {K, F}`
      tinyvm-bundled.luau  self-contained: micro-VM + AST + op helpers
    examples/              example programs you can run via tinyvm.py
      split-deploy/        Option 2 (split deploy) end-to-end example
      json-deploy/         all-JSON input plane end-to-end example
    tests/internal/        test suite
    docs/                  format spec + architecture notes


## Quickstart

```bash
# 1. Build the macro-VM AST and the self-contained bundle.
python tools/build.py

# 2. Compile and run a Luau source file.
python tools/tinyvm.py run examples/fibonacci.luau

# 3. Or compile a .luau to bytecode and run it yourself.
python tools/tinyvm.py compile examples/fibonacci.luau out.bin
```

Running the full test suite:

```bash
python tools/test.py
```


## Using it in your own Luau code

### Option 1: Self-contained bundle (simplest)

After `python tools/build.py`, `build/tinyvm-bundled.luau` is a single
file you can drop into your project. It returns a function:

```lua
local play = require("./tinyvm-bundled")
-- play(userBytecode, env, label, ...)
-- userBytecode: string produced by tools/compiler.py
-- env:          table providing globals to the user program
-- label:        short string used in error messages
-- ...:          extra args forwarded to the user program's main chunk

local userBytecode = "..."  -- the .bin compiled offline
local env = setmetatable({}, {__index = _G})  -- writable shadow of _G
env._G = env
play(userBytecode, env, "myscript.luau")
```

The bundle wraps your `env` in a shadow table that exposes the op-helper
functions (`B1`..`B14` for binary ops, `U1`..`U3` for unary ops) the
predecoder rewrote BinOp/UnOp atoms into; the shadow `__index`-falls
through to your `env`, which in turn typically falls through to `_G`.

### Option 2: Split deploy (smallest user-facing source)

If the Luau source size you ship matters and you can supply the
macro-VM data through another channel:

```lua
local micro    = require("./tinyvm")             -- 1955-byte module
local ast      = require("./macrovm-ast")        -- returns {K, F}
local K, F     = ast[1], ast[2]
local env      = ...   -- shadow env with B1..B14, U1..U3 + user globals
local tp, tu   = table.pack, table.unpack

-- micro(K, F, env, tp, tu, userBytecode, userEnv, label, ...)
micro(K, F, env, tp, tu, userBytecode, userEnv, label)
```

`build/macrovm-ast.luau` is a ready-to-use ModuleScript-style file that
returns `{K, F}` — it's a Lua expression, not raw bytes. The build
pipeline produces it from `src/macrovm.luau` via `tools/predecode.py`.
Wire it up in your own way (an asset, a `ModuleScript`, a generated
string literal, etc.).

Notes:

* The third argument to `micro` is the env the **macro-VM** uses to
  resolve its own globals (`string.byte`, `error`, plus the op helpers
  `B1`..`B14`, `U1`..`U3`). It must contain those names or fall through
  to a table that does. The bundle's `_E(e)` helper builds one for you.
* The 7th argument (the user's env) is what user code sees as its `_G`.
  It's just a normal table.

The bundle (Option 1) is the recommended path unless source size is
critical. See [`examples/split-deploy/`](examples/split-deploy/) for a
complete, runnable example of this recipe — including the launcher
script you'd write, a sample user program, and a driver that assembles
the staged module tree.

### Option 3: All-JSON deploy

If you want every input tinyvm consumes to be JSON-serializable:
predecode the macro-VM AST and the user program both to JSON, decode
them at runtime, and feed the resulting tables to the micro-VM.

```bash
# 1. Predecode the macro-VM with the micro-VM-specific rewrites.
python tools/predecode.py build/macrovm.bin macrovm-ast.json --for-micro --json

# 2. Predecode the user program WITHOUT --for-micro: the macro-VM (not
#    the micro-VM) consumes it, so only macro-VM-compatible atoms are OK.
python tools/compiler.py myscript.luau myscript.bin
python tools/predecode.py myscript.bin myscript-ast.json --json
```

Both files are JSON documents of the shape `[K, F]`. At runtime your
launcher decodes them, builds the same shadow env as in Option 2, and
calls:

```lua
local userAst = json.decode(...)   -- {K, F}
-- The macro-VM detects type(b)=="table" and skips its bytecode reader.
micro(macroK, macroF, shadowEnv, tp, tu, userAst, userEnv, "myscript.luau")
```

See [`examples/json-deploy/`](examples/json-deploy/) for a complete,
runnable example -- launcher, JSON decoder, and driver that assembles
the staged module tree.


## How small is it really?

Source-line counts:

```
src/tinyvm.luau          1955 bytes  ← the deliverable
src/macrovm.luau         6873 bytes  ← reference; gets compiled away
build/macrovm.bin        5850 bytes  ← compact bytecode form of macrovm.luau
build/macrovm-ast.luau  ~22600 bytes ← pre-decoded as Lua source (or JSON)
build/tinyvm-bundled.luau ~25700 bytes ← micro-VM + AST + helpers (drop-in)
```

The 1955-byte figure covers the entire tree-walker: expression
evaluation, multi-return / multi-assign, table construction, closure
binding (via `Q`, which builds upvalues from pure-data records), all
five flavors of loop, `if`/`elseif`/`else`, `return`/`break`, and
global/local/upvalue/index assignment. Removing any of these breaks
the macro-VM that runs on top of it.


## Constraints

* **No `loadstring` / `load`.** Roblox restricts these on the client; the
  whole design avoids them.
* **Build-time pre-decoding is required.** Earlier revisions of the
  micro-VM shipped a bytecode reader; this version does not. The macro-VM
  AST is supplied as `(K, F)` Lua tables — pure data, no function
  literals — produced by `tools/predecode.py`. If you invoke
  `tools/build.py`, this happens automatically.
* **The op-helper env is required.** The predecoder rewrites every
  BinOp/UnOp atom in the macro-VM into a Call atom that looks up
  `B1`..`B14` / `U1`..`U3` in the env. Your env must expose them. The
  bundled file does this for you.
* **The macro-VM is a specific Luau program.** As shipped, the micro-VM
  is matched to the atom set `src/macrovm.luau` emits after the
  predecoder runs. If you want to swap in a completely different
  interpreter, you'll need to mirror the same rewrite passes (or extend
  the micro-VM accordingly).


## See also

* `docs/architecture.md` — what the micro-VM does, what the predecoder
  rewrites, and why the trick works.
* `docs/bytecode-format.md` — the wire format the offline compiler emits
  and the rewrites the predecoder applies on top of it.
* `docs/limitations.md` — features that *don't* work and why.
