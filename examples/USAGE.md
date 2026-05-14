# Embedding tinyvm in your project

Three ways to use it, ordered from simplest to most flexible.

## 1. Run a Luau program from disk (development)

```bash
python tools/tinyvm.py run mygame.luau
```

This compiles `mygame.luau`, generates a runner, and shells out to `luau`.
Good for development. Not what you ship.

## 2. Drop in the bundle (single file, ship-ready)

After `python tools/build.py`, copy `build/tinyvm-bundled.luau` into
your Luau project. It's a ~28 KB single file containing the micro-VM,
the pre-decoded macro-VM AST, the op-helper env wrapper, and `tp`/`tu`
all wired up.

In your code:

```lua
local play = require("./tinyvm-bundled")

-- userBytecode is a string of bytes produced by:
--    python tools/tinyvm.py compile myscript.luau out.bin
local userBytecode = "..."  -- you supply this

-- The env is the global-namespace table the user program sees.
-- A writable shadow of _G is usually what you want.
local env = setmetatable({}, {__index = _G})
env._G = env

-- Run. play(...) does not return the user program's return values
-- (see docs/limitations.md); raised errors still propagate.
play(userBytecode, env, "myscript.luau")
```

The third argument (`"myscript.luau"`) is the chunk label shown in
`error()` messages. Make it meaningful.

## 3. Split deploy (smallest user-facing source)

If the size of the Luau source you ship matters more than the size of
the macro-VM data, ship just `src/tinyvm.luau` (1.7 KB) and load the
predecoded macro-VM AST through a separate channel. The micro-VM
signature is:

```lua
micro(K, F, E, tp, tu, userBytecode, userEnv, label, ...)
```

* `K, F` — the constant pool and function-builder array from
  `build/macrovm-ast.luau` (a Lua expression, not bytes).
* `E` — env table the macro-VM uses for its own globals (must include
  the op helpers `B1`..`B14` and `U1`..`U3`).
* `tp, tu` — `table.pack` and `table.unpack`.
* `userBytecode, userEnv, label, ...` — passed through to the macro-VM
  main closure.

Concrete example wiring it up yourself:

```lua
local micro       = require("./tinyvm")              -- the 1713-byte module
local K, F        = require("./macrovm-ast")         -- the pre-decoded AST
local tp, tu      = table.pack, table.unpack

local userEnv     = setmetatable({}, {__index = _G})
userEnv._G        = userEnv

-- Build the shadow env exposing the op helpers; falls through to userEnv.
local shadowEnv = setmetatable({
    B1  = function(a, b) return a + b end,
    B2  = function(a, b) return a - b end,
    B3  = function(a, b) return a * b end,
    B4  = function(a, b) return a / b end,
    B5  = function(a, b) return a // b end,
    B6  = function(a, b) return a % b end,
    B7  = function(a, b) return a ^ b end,
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

local userBytecode = "..."  -- bytes from tools/compiler.py

micro(K, F, shadowEnv, tp, tu, userBytecode, userEnv, "myscript.luau")
```

The macro-VM AST is a plain Lua module. Where it lives is up to you:

* As `macrovm-ast.luau` next to your shipped script: `require` it.
* As a `ModuleScript` in Roblox: `require(script.MacroVMAst)`.
* As a generated string literal embedded in your code at build time.
* As a `HttpService:GetAsync` response, an asset, etc.

Note that `macrovm-ast.luau` is ~25 KB of Lua source — larger than
the bytecode it was decoded from. The trade is: the micro-VM no
longer needs a runtime bytecode reader (saving ~1.5 KB of micro-VM
source), and per-function closure setup is baked into the AST itself
(saving another ~200 bytes). If you'd rather ship the smaller raw
bytecode and run a reader at load time, see the git history before
the `experimental-sub2k` branch.

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

The bytecode is a flat binary blob. You can ship it as a file, embed it
in a Lua string literal, hash it for asset-pipeline purposes, anything
you'd do with a normal byte string.

## What the env table needs

The user program sees the env table as its `_G`. At minimum populate it
with whatever standard library functions and host APIs the user program
needs:

```lua
local env = setmetatable({}, {__index = _G})
env._G = env

-- Optional: restrict what the user program can access.
-- env._G now shadows _G, so writes go to env and don't leak.

-- If you want to give the user access to your own host APIs:
env.myGameAPI = {
    spawnEntity = function(x, y) ... end,
    killEntity  = function(id) ... end,
}
```

If you want a truly sandboxed environment, set the `__index` metatable
of `env` to a curated table instead of `_G`.

This is the **user's** env (the 7th argument to the micro-VM, or the
2nd argument to the bundle's `play(...)`). The micro-VM's 3rd argument
is the env the macro-VM uses internally — they're different tables.
The bundle handles this for you.

## Error handling

User errors (uncaught) propagate out of `play(...)` as normal Lua errors,
prefixed with `<label>:<line>:` like the standard VM does. Wrap the call
in `pcall` if you need to recover.

```lua
local ok, err = pcall(play, userBytecode, env, "myscript.luau")
if not ok then
    -- err is a string like "myscript.luau:42: attempt to call a nil value"
    warn("script crashed:", err)
end
```
