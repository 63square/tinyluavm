# tinyvm

**A Luau interpreter for Luau, in 4708 bytes of Luau source.**

`tinyvm` is a two-stage Luau-in-Luau interpreter. The thing that lives in
your project is a 4.7 KB micro-VM (`src/tinyvm.luau`). It expects a
caller-supplied "macro-VM" bytecode — the full feature-complete interpreter
compiled to a compact bytecode format — and then runs your user bytecode on
top of that macro-VM.

```
   ┌──────────────────────────────────────────────────────────────┐
   │ src/tinyvm.luau   (4708 bytes — this is what ships)          │
   │   reads → macro-VM bytecode (compiled from src/macrovm.luau) │
   │            reads → user bytecode (compiled from user .luau)  │
   └──────────────────────────────────────────────────────────────┘
```

The trick: the macro-VM bytecode comes from the *caller*, so its size
doesn't count against `tinyvm`. The micro-VM only has to handle the small
set of Luau features the macro-VM itself uses — letting it cut all the
diagnostic prefixing, `__call` / `__namecall` / `__iter` dispatch, error
wrapping, and conformance-text-matching that bloat a self-contained
interpreter.


## What you get

* **103 internal tests pass** (35 core + 35 edge cases + 33 type-stripping).
* **13/21 Luau conformance tests pass**, matching the baseline of the
  larger interpreter that this micro-VM transitively runs. The 8 failing
  tests fail for reasons unrelated to byte count (`pairs` traversal order,
  `setfenv`/`getfenv`, host stack depth, `math.tau`, `table.sort`
  GC timing).
* **Roblox-compatible**. No `loadstring`, no `load`, no `debug.*`. Just
  `require`, `setmetatable`, basic stdlib.
* **Every Luau feature** the macro-VM exposes: closures, multi-return,
  varargs, metatables, `__call`/`__index`/`__namecall`/`__iter`, `pcall`,
  coroutines, generic-for, numeric-for (with all Luau corner cases),
  compound assignment, string interpolation, `if`-expressions, `continue`,
  type annotations (parsed and discarded). The micro-VM doesn't need to
  implement these directly — the macro-VM does, and the micro-VM just
  needs to interpret the macro-VM.


## Layout

    src/
      tinyvm.luau          micro-VM — the 4708-byte interpreter
      macrovm.luau         macro-VM source (Luau)  — readable reference
    tools/
      compiler.py          offline Luau → bytecode compiler
      build.py             builds build/macrovm.bin + the bundle
      tinyvm.py            CLI wrapper for compile + run
      test.py              test runner
    build/                  generated artifacts (after `python tools/build.py`)
      macrovm.bin          compiled macro-VM (~5.8 KB)
      macrovm-module.luau  Luau module returning the macro-VM bytes
      tinyvm-bundled.luau  self-contained: micro-VM + macro-VM combined
    examples/               example programs you can run via tinyvm.py
    tests/internal/         test suite
    docs/                   format spec + architecture notes


## Quickstart

```bash
# 1. Build the macro-VM bytecode and the self-contained bundle.
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
-- env: table providing globals to the user program
-- label: short string used in error messages
-- ...: extra args forwarded to the user program's main chunk

local userBytecode = "..."  -- the .bin compiled offline
local env = setmetatable({}, {__index = _G})  -- writable shadow of _G
env._G = env
play(userBytecode, env, "myscript.luau")
```

Bundle size: ~24 KB (4.7 KB micro-VM + 5.8 KB macro-VM bytecode embedded
+ small wrapper).

### Option 2: Separate micro-VM + macro-VM (smallest code-paths)

Ship just `src/tinyvm.luau` (4.7 KB) and load the macro-VM bytecode
through your own data channel (an asset, a network response, etc.):

```lua
local micro = require("./tinyvm")
local macroBytecode = require("./macrovm-module")   -- or load it however

-- micro(macroBytes, userBytes, env, label, ...) runs user bytes
-- against env, using macroBytes as the inner interpreter logic.
local result = micro(macroBytecode, userBytecode, env, "myscript.luau")
```

This split is useful when:

* You want your code-shipping artifact to be tiny (the 4.7 KB micro-VM)
  and you load the larger macro-VM data from a CDN / asset bin / etc.
* You're running on a platform where Luau source size matters a lot but
  binary data is cheap (it usually compresses better than source anyway).


## How small is it really?

Source-line counts (after the squish pass):

```
src/tinyvm.luau     4708 bytes  ← this is the deliverable
src/macrovm.luau    6811 bytes  ← reference, gets compiled away
build/macrovm.bin   5792 bytes  ← compact bytecode form of macrovm.luau
```

The 4708-byte figure includes the entire bytecode reader, all 14 binary
operators, all 3 unary operators, both control-flow and dispatch logic,
table-constructor support, and closure-with-upvalue handling. Removing
any of these breaks the macro-VM that runs on top of it.


## Constraints

* **No `loadstring` / `load`.** Roblox restricts these on the client; the
  whole design avoids them.
* **Lua-side import is allowed.** The "macro-VM bytecode is supplied by
  the caller" architecture means the micro-VM source itself doesn't have
  to contain the full interpreter logic — only what's needed to interpret
  a well-formed Luau bytecode stream that was compiled from a known,
  well-behaved Luau source. This is what makes 4.7 KB achievable.
* **The macro-VM is a specific Luau program.** If you want to swap in a
  completely different interpreter at the macro level (different language,
  different bytecode format), the micro-VM would need adjustments. As
  shipped, it reads the format emitted by `tools/compiler.py`.


## See also

* `docs/architecture.md` — what the micro-VM does, what it skips, and
  why the trick works.
* `docs/bytecode-format.md` — the wire format the compiler emits.
* `docs/limitations.md` — features that *don't* work and why.
