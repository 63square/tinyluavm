# Embedding tinyvm in your project

Three ways to use it, ordered from simplest to most flexible.

## 1. Run a Luau program from disk (development)

```bash
python tools/tinyvm.py run mygame.luau
```

This compiles `mygame.luau`, predecodes it together with the macro-VM,
generates a runner, and shells out to `luau`. Good for development.
Not what you ship.

## 2. Split deploy (three Luau modules)

Ship three Luau modules side by side: the micro-VM, the predecoded
macro-VM AST, and the predecoded user-program AST. Your launcher
`require()`s them, builds the env, and calls `micro(...)`.

The micro-VM signature is:

```lua
micro(env, inputData, userEnv, label)
```

* `env` — env table the macro-VM uses for its own globals. Must
  include the op helpers `B1`..`B14` (binary ops) and `U1`..`U3`
  (unary ops). A shadow env with `__index = userEnv` is the usual
  shape.
* `inputData` — `{m = macroAst, u = userAst}` where each entry is
  `{K, F}` (a constant pool + function records list, produced by
  `tools/predecode.py`).
* `userEnv` — the table the user program sees as its `_G`.
* `label` — chunk name shown in `error()` diagnostics.

Concrete example wiring it up yourself:

```lua
local micro   = require("./tinyvm")               -- 1997-byte module
local mvmAst  = require("./macrovm-ast")          -- returns {K, F}
local userAst = require("./user-ast")             -- returns {K, F}

local userEnv = setmetatable({}, {__index = _G})
userEnv._G    = userEnv

-- Shadow env exposing the op helpers; falls through to userEnv -> _G.
local shadowEnv = setmetatable({
    B1  = function(a, b) return a + b  end,
    B2  = function(a, b) return a - b  end,
    B3  = function(a, b) return a * b  end,
    B4  = function(a, b) return a / b  end,
    B5  = function(a, b) return a // b end,
    B6  = function(a, b) return a % b  end,
    B7  = function(a, b) return a ^ b  end,
    B8  = function(a, b) return a .. b end,
    B9  = function(a, b) return a == b end,
    B10 = function(a, b) return a ~= b end,
    B11 = function(a, b) return a <  b end,
    B12 = function(a, b) return a <= b end,
    B13 = function(a, b) return a >  b end,
    B14 = function(a, b) return a >= b end,
    U1  = function(a) return -a end,
    U2  = function(a) return not a end,
    U3  = function(a) return #a end,
}, {__index = userEnv})

micro(shadowEnv, {m = mvmAst, u = userAst}, userEnv, "myscript.luau")
```

See [`split-deploy/`](split-deploy/) for a complete runnable example
including a driver that compiles + predecodes everything and stages
the four files in `staged/`.

## 3. All-JSON deploy (one JSON document)

If you want every input tinyvm consumes to be JSON-encodable (no
binary bytecode, no Lua-syntax-only modules), pre-decode the macro-VM
and your user program together with `--user --json`:

```bash
python tools/compiler.py myscript.luau myscript.bin
python tools/predecode.py build/macrovm.bin payload.json \
    --for-micro --json --user myscript.bin
```

`payload.json` is a single document of shape:

```json
{"m": [<macroK>, <macroF>], "u": [<userK>, <userF>]}
```

— pure data: numbers, strings, booleans, nulls, arrays, objects. At
runtime your launcher decodes it with any JSON parser and passes the
resulting table directly to `micro(...)` as the `inputData` argument:

```lua
local micro     = require("./tinyvm")
local decode    = require("./jsondec")           -- bring-your-own
local inputData = decode(loadPayloadJsonSomehow())

-- ... build shadowEnv and userEnv as in section 2 ...

micro(shadowEnv, inputData, userEnv, "myscript.luau")
```

See [`json-deploy/`](json-deploy/) for a complete runnable example
including a tiny JSON parser.

## Compiling user programs

The compiler is a pure Python script with no dependencies beyond the
standard library. From the command line:

```bash
python tools/compiler.py myscript.luau myscript.bin
```

Or programmatically from Python:

```python
from compiler import compile_source
with open("myscript.luau") as f:
    bytecode = compile_source(f.read())  # returns bytes
```

The bytecode is a flat binary blob. It's an intermediate artifact;
to feed it to the micro-VM you still need to predecode it with
`tools/predecode.py`.

## What the user env table needs

The user program sees the user env as its `_G`. At minimum populate it
with whatever standard library functions and host APIs the user program
needs:

```lua
local userEnv = setmetatable({}, {__index = _G})
userEnv._G    = userEnv

-- Optional: restrict what the user program can access.
-- userEnv._G now shadows _G, so writes go to userEnv and don't leak.

-- If you want to give the user access to your own host APIs:
userEnv.myGameAPI = {
    spawnEntity = function(x, y) ... end,
    killEntity  = function(id) ... end,
}
```

If you want a truly sandboxed environment, set the `__index` metatable
of `userEnv` to a curated table instead of `_G`.

Note that the **shadow env** (`micro`'s first argument) is *not* the
same table as the user env. The shadow env carries the op-helper
functions the macro-VM needs internally; the user env is what user code
sees as `_G`. The shadow env's `__index` falls through to the user env,
so user globals work transparently.

## Error handling

User errors (uncaught) propagate out of `micro(...)` as normal Lua
errors, prefixed with `<label>:<line>:` like the standard VM does.
Wrap the call in `pcall` if you need to recover.

```lua
local ok, err = pcall(micro, shadowEnv, inputData, userEnv, "myscript.luau")
if not ok then
    -- err is a string like "myscript.luau:42: attempt to call a nil value"
    warn("script crashed:", err)
end
```
