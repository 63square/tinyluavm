# `json-deploy` example

A complete, runnable example of feeding tinyvm an entirely JSON-encodable
input plane: the macro-VM AST and the user program are pre-decoded
**together** into a single JSON document, the launcher decodes that one
string at startup, and the micro-VM gets a pure-data `inputData` table.

Useful when:

* You want a single, well-known serialization format (JSON) for the
  whole payload tinyvm consumes — no binary bytecode files, no
  Lua-syntax-only modules, just one JSON string you can store anywhere.
* You want to ship the macro-VM AST and your user program over a wire
  that only carries text (REST APIs, message queues, MessagePack-via-
  JSON gateways, etc.).


## Layout

```
examples/json-deploy/
├── README.md              you are here
├── build_and_run.py       driver: predecode + JSON-wrap + run luau
├── launcher.luau          ★ the launcher: requires the modules, decodes
├── jsondec.luau           ~80-line JSON parser (object/array/string/number)
├── user.luau              a sample user program
└── staged/                ↑ assembled by build_and_run.py, gitignored
    ├── tinyvm.luau            copy of src/tinyvm.luau
    ├── jsondec.luau           copy of ../jsondec.luau
    ├── launcher.luau          copy of ../launcher.luau
    └── payload-json.luau      ModuleScript: returns {<json string>}
```

The `payload-json.luau` module just wraps the JSON document in a
1-element table (Roblox / standalone `luau` requires `require()`
returns to be tables or functions, not bare strings). That wrapper
is the **only** non-JSON part of the payload, and it's trivial.


## Run it

```bash
python examples/json-deploy/build_and_run.py
```

Expected output:

```
[json-deploy] predecoded macro-VM + user.luau -> payload.json (19319 bytes)
[json-deploy] wrapped JSON payload as a Luau module
[json-deploy] staged tinyvm.luau (2472 bytes), jsondec.luau, launcher.luau
[json-deploy] invoking luau on staged/launcher.luau
============================================================
== launcher: running user.luau (all data plane is JSON) ==
hello from tinyvm-json-deploy-example v1.0
counter: 1, 2, 3
basket total: 1.85
v = Vec(4,6)
pcall returned ok=false err=user.luau:34: intentional
user.luau done
== launcher: user program finished cleanly ==
============================================================
[json-deploy] done
```


## How it works

### Build pipeline (offline, in Python)

1. `tools/compiler.py` compiles `src/macrovm.luau` to `macrovm.bin`
   (already done by `tools/build.py` — the driver reuses it).
2. `tools/compiler.py` compiles `user.luau` to a temporary `.bin`.
3. `tools/predecode.py build/macrovm.bin staged/payload.json
   --for-micro --json --user user.bin` predecodes both into a single
   combined JSON document:

   ```json
   {
     "m": [<macroK>, <macroF>],
     "u": [<userK>,  <userF>]
   }
   ```

   The macro half has the micro-VM-specific rewrites applied
   (`--for-micro`); the user half does not (the macro-VM consumes
   the user AST at runtime and expects its native atom shape).

The result is one JSON file, pure data: arrays, objects, strings,
numbers, `true`, `false`, `null`. No functions, no userdata, no
Lua-specific constructs.

### Runtime pipeline (inside luau)

1. The launcher `require()`s the wrapper module and gets a single
   JSON string.
2. It decodes the string with `jsondec.luau` (a small JSON parser).
3. It calls the micro-VM. (The micro-VM handles BinOp/UnOp atoms
   natively — no shadow env or op helpers needed.)

   ```lua
   micro(inputData, userEnv, "user.luau")
   ```

   `inputData` is the decoded `{m=..., u=...}` table.


## The user AST is also JSON

The `user.luau` source compiles to ~750 bytes of bytecode; the
predecoder turns that into ~1.7 KB of JSON. The JSON is bigger than
the raw bytecode (varints are denser than decimal digits), but you can
pipe it through any JSON-handling tool: pretty-print it, grep it,
diff two versions of the same script, transform it with `jq`, etc.

Sample slice of the combined payload:

```json
{
  "m": [
    ["table", "pack", "unpack", "getmetatable", ..., true, false],
    [
      {"np": 0, "va": 1, "L": [], "b": [50, [...], [...]]},
      ...
    ]
  ],
  "u": [
    [2, 1, 0, 12, "print", "fib(", "tostring", ") = ", null],
    [
      {"np": 0, "va": 1, "L": [], "b": [50, [...], [...]]},
      {"np": 1, "va": 0, "L": [[0, 1]], "b": [50, [...], [...]]}
    ]
  ]
}
```

* The two top-level keys `m` and `u` match the micro-VM's accesses
  (`D.m` for the macro-VM AST, `D.u` for the user-program AST).
* Each inner `[K, F]` is the usual `K` (constants) + `F`
  (function records) pair.
* Function records are objects `{np, va, L, b}`:
  `np` = number of params, `va` = vararg flag (0/1), `L` = upvalue
  source list, `b` = body atom tree.

See `docs/bytecode-format.md` for the full atom-tag reference.


## Where this fits in the deployment matrix

|                                  | split deploy             | json deploy (this)               | http deploy                     |
|----------------------------------|--------------------------|----------------------------------|---------------------------------|
| Macro-VM data lives in           | ModuleScript             | ModuleScript                     | HTTP endpoint                   |
| User program lives in            | ModuleScript             | ModuleScript                     | HTTP endpoint                   |
| Wire format                      | Luau syntax              | JSON                             | JSON                            |
| Update flow                      | re-publish Roblox        | re-publish Roblox                | push to server, no redeploy     |
| Network dependency               | none                     | none                             | yes (HttpService)               |
| Launcher boilerplate             | ~25 lines                | ~25 lines + a JSON parser        | ~25 lines + JSON parser + httpGet |
| Source code can be diffed/jq'd?  | partially                | yes -- everything                | yes -- everything               |

If you want JSON-style transport for all the data tinyvm consumes,
this example is the recipe. Use [http-deploy](../http-deploy/) if you
also want runtime fetching. Otherwise the split deploy is more
compact (no JSON parser).


## Customizing

* **Streaming**: see [http-deploy](../http-deploy/) for the same JSON
  payload served and fetched over HTTP at runtime.
* **Restricting the user env**: replace the `__index = _G` chain with
  a curated table to sandbox.
* **Replacing the JSON parser**: any JSON parser that produces nested
  Lua tables, with string keys for objects and 1-based int keys for
  arrays, mapping `null` to `nil`, works. The `jsondec.luau` bundled
  here is just one possible choice.
