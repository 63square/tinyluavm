--!nocheck
-- Split-deploy launcher for tinyvm (the "Option 2" recipe from the README).
--
-- This is what you write yourself when you want to ship the micro-VM source
-- separately from the macro-VM AST, instead of using the all-in-one bundle.
-- It loads three things:
--
--   1. The 1713-byte micro-VM     -> ./tinyvm.luau         (copied from src/)
--   2. The pre-decoded macro-VM   -> ./macrovm-ast.luau    (from build/)
--   3. The compiled user bytecode -> ./user_bytecode.luau  (a module returning
--                                                          the hex-decoded bin)
--
-- and wires up the shadow environment so the op-helper functions the
-- predecoder rewrote BinOp/UnOp into resolve correctly.
--
-- In a real Roblox project these three modules would live anywhere — in
-- this example they're laid out flat next to this file so plain
-- `require("./...")` works.
local micro     = require("./tinyvm")
local ast       = require("./macrovm-ast")    -- returns {K, F}
local userMod   = require("./user_bytecode")  -- returns {hexString}

local K, F      = ast[1], ast[2]
local userHex   = userMod[1]
local tp, tu    = table.pack, table.unpack

-- Decode the hex string back to a byte string. We keep it as hex in source
-- because raw 8-bit string literals in Luau source need escaping anyway;
-- this is easier to copy-paste through diff tools and ModuleScript editors.
local function hexDecode(s: string): string
    local out = table.create(#s // 2)
    for i = 1, #s, 2 do
        out[#out + 1] = string.char(tonumber(string.sub(s, i, i + 1), 16))
    end
    return table.concat(out)
end

-- ---------------------------------------------------------------------------
-- Build the env the *user program* sees as its globals. A writable shadow
-- of _G is usually what you want: the user can read everything stdlib gives
-- them, and writes don't leak into the host's _G.
-- ---------------------------------------------------------------------------
local userEnv = setmetatable({}, {__index = _G})
userEnv._G = userEnv

-- (Optional) restrict or extend what the user can see. Anything you stick
-- on `userEnv` is visible to the user program as a global. Anything you
-- *don't* add and that's not on `_G` is invisible.
userEnv.hostInfo = {
    appName    = "tinyvm-split-deploy-example",
    appVersion = "1.0",
}

-- ---------------------------------------------------------------------------
-- Build the env the *macro-VM* uses internally. It needs:
--   * the standard-library globals it references (string.byte, table.pack,
--     getmetatable, error, ...)   -- via __index fallthrough
--   * the B1..B14 / U1..U3 helpers that the predecoder rewrote arithmetic
--     atoms into                  -- defined here
-- ---------------------------------------------------------------------------
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

-- ---------------------------------------------------------------------------
-- Run the user program.
--
-- Signature: micro(K, F, E, tp, tu, userBytecode, userEnv, label, ...)
--   K, F          - the predecoded macro-VM AST
--   E             - the env the macro-VM uses (shadowEnv: op helpers + fallthrough)
--   tp, tu        - table.pack / table.unpack
--   userBytecode  - the offline-compiled .bin as a string
--   userEnv       - what the user program sees as its _G
--   label         - chunk name shown in diagnostic messages
--   ...           - extra args forwarded to the user program's main chunk
-- ---------------------------------------------------------------------------
local userBytecode = hexDecode(userHex)

print("== launcher: starting user program ==")
local ok, err = pcall(
    micro, K, F, shadowEnv, tp, tu, userBytecode, userEnv, "user.luau"
)
if not ok then
    print("== launcher: user program raised an error ==")
    print(tostring(err))
else
    print("== launcher: user program finished cleanly ==")
end
