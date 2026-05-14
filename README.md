# tinyvm

**A Luau interpreter for Luau, in 2472 bytes of Luau source.**

`tinyvm` is a two-stage Luau-in-Luau interpreter. The thing that lives in
your project is a 2.5 KB micro-VM (`src/tinyvm.luau`). It expects a
caller-supplied "macro-VM" — the full feature-complete interpreter,
pre-decoded at build time into pure-data `(K, F)` tables — and runs
your user code through it.

Every input to the micro-VM is a plain Lua value (number, string, bool,
nil, table). There are no userdata, no function literals, no opaque
blobs. The macro-VM AST and the user program (also pre-decoded) round-
trip losslessly through JSON.

```
   ┌──────────────────────────────────────────────────────────────────┐
   │ src/tinyvm.luau   (2472 bytes — this is what ships)              │
   │   interprets → macro-VM AST  (pre-decoded from src/macrovm.luau) │
   │                  interprets → user AST (pre-decoded from .luau)  │
   └──────────────────────────────────────────────────────────────────┘
```

The trick: both the macro-VM AST and the user-program AST are *data*
that the caller supplies — they don't count against the size of the
shipped `tinyvm.luau`. The micro-VM only has to handle the small subset
of Luau features the macro-VM itself uses, and most of those are further
reduced by build-time atom rewrites that fold opcodes the micro-VM
would otherwise need to dispatch.


## What you get

* **103 internal tests pass** (35 core + 35 edge cases + 33 type-stripping).
* **All example programs pass** (closures, coroutines, fibonacci,
  hello, metatables).
* **Roblox-compatible**. No `loadstring`, no `load`, no `debug.*`. Just
  `require`, `setmetatable`, basic stdlib.
* **Every Luau feature** the macro-VM exposes: closures, multi-return,
  varargs, metatables, `__call`/`__index`/`__namecall`/`__iter`, `pcall`,
  coroutines, generic-for, numeric-for (with all Luau corner cases),
  compound assignment, string interpolation, `if`-expressions, `continue`,
  type annotations (parsed and discarded). The micro-VM doesn't need to
  implement these directly — the macro-VM does, and the micro-VM just
  needs to interpret the macro-VM.
* **JSON-encodable input plane**. The macro-VM AST and the user program
  AST combine into a single `inputData` payload — pure data, JSON
  serializable, diffable, hashable, transformable with `jq`.
* **Simple 3-argument API**. The caller passes the combined `inputData`,
  a plain user env, and a chunk label. No shadow env construction, no
  op-helper wiring.


## Layout

    src/
      tinyvm.luau          micro-VM — the 2472-byte interpreter
      macrovm.luau         macro-VM source (Luau) — readable reference;
                           compiled and pre-decoded at build time
    tools/
      compiler.py          offline Luau → bytecode compiler
      predecode.py         compiles a .bin into a Luau module (or JSON,
                           with --json) of shape {K, F}. With --user
                           also predecodes a user program and emits a
                           combined `{m={K,F}, u={K,F}}` payload.
      build.py             builds build/macrovm.bin and build/macrovm-ast.luau
      tinyvm.py            CLI wrapper: compile + run a single .luau file
      test.py              test runner
    build/                 generated artifacts (after `python tools/build.py`)
      macrovm.bin          compiled macro-VM bytecode (reference only)
      macrovm-ast.luau     pre-decoded macro-VM as `return {K, F}`
    examples/              example programs and end-to-end recipes
      split-deploy/        split deploy: separate modules for tinyvm,
                           macro-VM AST, user-program AST
      json-deploy/         all-JSON: single combined JSON document
                           covering everything


## API

The micro-VM is a single function:

```lua
micro(inputData, userEnv, label)
```

| argument    | what it is                                                       |
|-------------|------------------------------------------------------------------|
| `inputData` | `{m = macroAst, u = userAst}` where each is `{K, F}`             |
| `userEnv`   | what user code sees as its `_G`; usually a writable shadow of    |
|             | `_G`. The macro-VM resolves its own globals (`string`, `table`,  |
|             | `error`, ...) through the same table.                            |
| `label`     | chunk name shown in `error()` diagnostics                        |

`table.pack`, `table.unpack`, and the arithmetic-op handlers are
implemented inside the micro-VM; you don't pass them in.


## Quickstart

```bash
# 1. Build the macro-VM and predecode it.
python tools/build.py

# 2. Compile and run a Luau source file.
python tools/tinyvm.py run examples/fibonacci.luau

# 3. Or compile a .luau to bytecode on its own.
python tools/tinyvm.py compile examples/fibonacci.luau out.bin
```

Running the full test suite:

```bash
python tools/test.py
```


## Using it in your own Luau code

There are two deployment recipes shipped as runnable examples; both
have the same shape and only differ in how the data is transported.

### Split deploy (separate modules)

Ship three Luau modules: `tinyvm`, the predecoded macro-VM AST, and
the predecoded user-program AST. Your launcher `require()`s the three
and combines the two ASTs into `inputData`. Code lives in
[`examples/split-deploy/`](examples/split-deploy/).

```lua
local micro   = require("./tinyvm")
local mvmAst  = require("./macrovm-ast")  -- returns {K, F}
local userAst = require("./user-ast")     -- returns {K, F}

local userEnv = setmetatable({}, {__index = _G})
userEnv._G = userEnv

micro({m = mvmAst, u = userAst}, userEnv, "user.luau")
```

### All-JSON deploy (one document)

Predecode the macro-VM and the user program together into one JSON
document of shape `{"m": [K, F], "u": [K, F]}`, then decode it at
runtime with any JSON parser. The launcher passes the decoded table
directly to the micro-VM as `inputData`. Code lives in
[`examples/json-deploy/`](examples/json-deploy/).

```bash
python tools/compiler.py myscript.luau myscript.bin
python tools/predecode.py build/macrovm.bin payload.json \
    --for-micro --json --user myscript.bin
```

```lua
local micro     = require("./tinyvm")
local decode    = require("./jsondec")
local inputData = decode(loadPayloadJsonSomehow())

local userEnv = setmetatable({}, {__index = _G})
userEnv._G = userEnv

micro(inputData, userEnv, "myscript.luau")
```


## How small is it really?

```
src/tinyvm.luau          2472 bytes  ← the deliverable
src/macrovm.luau         5221 bytes  ← reference; gets compiled away
build/macrovm.bin        4384 bytes  ← compact bytecode form of macrovm.luau
build/macrovm-ast.luau  ~15700 bytes ← pre-decoded as Lua source (or JSON)
```

The 2472-byte figure covers the entire tree-walker: expression
evaluation, all 14 binary operators, all 3 unary operators, multi-
return / multi-assign, table construction, closure binding (via `Q`,
which builds upvalues from pure-data records), all five flavors of
loop, `if`/`elseif`/`else`, `return`/`break`, and global/local/upvalue/
index assignment. Removing any of these breaks the macro-VM that runs
on top of it.


## Constraints

* **No `loadstring` / `load`.** Roblox restricts these on the client; the
  whole design avoids them.
* **Build-time pre-decoding is required for everything.** Both the
  macro-VM AST and the user program AST are pure-data tables produced
  by `tools/predecode.py`. There is no runtime bytecode reader.
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
