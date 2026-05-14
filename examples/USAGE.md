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
your Luau project. It's one ~24 KB file containing the micro-VM and the
macro-VM bytecode.

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

-- Run. Any return values from the user program's main chunk are returned here.
local result = play(userBytecode, env, "myscript.luau")
```

The third argument (`"myscript.luau"`) is the chunk label shown in
`error()` messages. Make it meaningful.

## 3. Split deploy (smallest user-facing source)

If size of the Luau source you ship matters more than the size of binary
data, ship just `src/tinyvm.luau` (4.7 KB) and load the macro-VM bytecode
through a separate channel:

```lua
local micro = require("./tinyvm")              -- 4708-byte module
local macroBytes = loadMacroVMBytecode()       -- you supply this loader
local result = micro(macroBytes, userBytecode, env, "myscript.luau")
```

The "loader" can read from anywhere: a Roblox `ModuleScript`, an
`HttpService:GetAsync` response, an asset file, a `string` literal you
generated at build time, etc. Binary data tends to compress better than
Lua source over the wire, so this split is worth it when transport size
dominates.

`build/macrovm-module.luau` is a ready-to-use `ModuleScript`-style file
that returns the macro-VM bytes as a string. You can:

```lua
local macroBytes = require("./macrovm-module")  -- returns the bytes string
```

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
