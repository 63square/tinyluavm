--!nocheck
-- All-JSON-deploy launcher for tinyvm.
--
-- Everything we feed into the micro-VM (the macro-VM AST and the user
-- program) is JSON-serialized. The launcher is responsible for:
--
--   1. Loading the JSON payloads as strings (here via `require()`s; in
--      a real project you'd HttpGet them, read them from an asset, etc.).
--   2. Decoding them with a JSON parser (we include a small one in
--      jsondec.luau).
--   3. Wiring up the shadow env that exposes the op-helper functions the
--      predecoder rewrote BinOp/UnOp atoms into.
--   4. Calling the micro-VM with the decoded structures.
--
-- The point of this example: the entire data-plane is JSON. You could
-- replace any of the require() calls with HttpService:GetAsync(), or with
-- a JSON payload pasted into a string literal at build time, etc.
local micro    = require("./tinyvm")
local decode   = require("./jsondec")

local macroAst = decode(require("./macrovm-ast-json")[1])
local userAst  = decode(require("./user-ast-json")[1])

local K, F   = macroAst[1], macroAst[2]
local tp, tu = table.pack, table.unpack

-- The env the user program sees as `_G`. A writable shadow of `_G` is
-- usually fine; restrict or extend as needed.
local userEnv = setmetatable({}, {__index = _G})
userEnv._G = userEnv
userEnv.hostInfo = {
    appName    = "tinyvm-json-deploy-example",
    appVersion = "1.0",
}

-- The shadow env exposes the op-helper functions the predecoder rewrote
-- BinOp/UnOp atoms into. The fallthrough chain is:
--   shadowEnv -> userEnv -> _G
local shadowEnv = setmetatable({
    B1  = function(a, b) return a + b  end,
    B2  = function(a, b) return a - b  end,
    B3  = function(a, b) return a * b  end,
    B4  = function(a, b) return a / b  end,
    B5  = function(a, b) return a // b end,
    B6  = function(a, b) return a %  b end,
    B7  = function(a, b) return a ^  b end,
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

-- The macro-VM can be fed either bytecode bytes (string) OR a pre-decoded
-- AST table. Here we pass the table directly -- no bytecode reader runs.
print("== launcher: running user.luau (all data plane is JSON) ==")
local ok, err = pcall(
    micro, K, F, shadowEnv, tp, tu, userAst, userEnv, "user.luau"
)
if not ok then
    print("== launcher: user program raised an error ==")
    print(tostring(err))
else
    print("== launcher: user program finished cleanly ==")
end
