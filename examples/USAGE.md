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
`require()`s them and calls `micro(...)`.

The micro-VM signature is:

```lua
micro(inputData, userEnv?)
```

* `inputData` — `{m = macroAst, u = userAst}` where each entry is
  `{K, F}` (a constant pool + function records list, produced by
  `tools/predecode.py`).
* `userEnv` — what user code sees as its globals namespace. Defaults
  to `getfenv(2)` (the caller's environment) when omitted, so the
  user program can read and write the caller's globals directly. The
  macro-VM resolves its own stdlib references (`string`, `table`,
  `error`, ...) through the same table.

Concrete example wiring it up yourself:

```lua
local micro   = require("./tinyvm")               -- 2485-byte module
local mvmAst  = require("./macrovm-ast")          -- returns {K, F}
local userAst = require("./user-ast")             -- returns {K, F}

micro({m = mvmAst, u = userAst}, getfenv())
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

micro(inputData, getfenv())
```

See [`json-deploy/`](json-deploy/) for a complete runnable example
including a tiny JSON parser.

## 4. HTTP deploy (payload fetched at runtime)

Same combined-JSON payload as Option 3, but served by an HTTP
endpoint and fetched at runtime by the launcher. Useful for hot-swap
deployment: push a new payload to the server, no Roblox-place re-
publish needed.

The launcher is essentially the JSON deploy launcher with the
"load payload" step replaced by an HTTP fetch:

```lua
local HttpService = game:GetService("HttpService")
local micro       = require(script.tinyvm)
local decode      = require(script.jsondec)

local body      = HttpService:GetAsync("https://your-server/payload.json")
local inputData = decode(body)

micro(inputData, getfenv())
```

See [`http-deploy/`](http-deploy/) for a complete runnable example
that ships a tiny Python HTTP server, plus an HTTP-GET shim that
lets the example run under sandboxed standalone `luau` (which has
no network stack) without changing the launcher's code.

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

## Picking an env table

The user program sees the `userEnv` table as its globals namespace.
The macro-VM looks up its own stdlib references (`string`, `table`,
`error`, `tostring`, ...) through the same table.

The simplest pick is `getfenv()`, which returns whatever environment
the calling script is running in. On Roblox that's the script-level
table with `_G` reachable through `__index`; on standalone `luau`
it's effectively `_G`. The launcher can write globals to it freely
and they show up as host APIs to the user program:

```lua
hostInfo = {appName = "my-game", version = "1.0"}
hostAPI  = {spawn = function(x, y) ... end}

micro(inputData, getfenv())
```

For a tighter sandbox build your own table with a curated `__index`:

```lua
local sandbox = setmetatable({
    -- only expose the bits you want
    print = print,
    string = string,
    math = math,
}, {__index = function(_, k) return nil end})

micro(inputData, sandbox)
```

## Error handling

User errors propagate out of `micro(...)` as normal Lua errors with
exactly the message the user code raised (`error("boom")` produces
`"boom"`). Wrap the call in `pcall` if you want to recover gracefully:

```lua
local ok, err = pcall(micro, inputData)
if not ok then
    -- err is the user-supplied message, e.g. "boom"
    warn("user program crashed: " .. tostring(err))
end
```

For full stealth (no Lua stack trace from the host runtime in the
fallthrough case), wrap with `pcall` and re-raise at level 0:

```lua
local ok, err = pcall(micro, inputData)
if not ok then error(err, 0) end
```
